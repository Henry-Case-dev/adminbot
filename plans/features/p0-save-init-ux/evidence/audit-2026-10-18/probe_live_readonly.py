"""Prod READ-ONLY live probe (PERSIST-AUDIT): что реально видит владелец.

Только GET. Никаких записей в prod (POST/PUT/DELETE запрещены линией).
initData подписывается локальным API_TOKEN (если прод использует тот же
BOT-токен — подпись валидна; иначе 401 и проба честно репортит это).

Запуск:
  .venv\\Scripts\\python.exe plans/features/p0-save-init-ux/evidence/audit-2026-10-18/probe_live_readonly.py
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import time
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

import urllib.request
import urllib.error

from config.settings import settings  # noqa: E402

BASE = os.environ.get("PROD_BASE", "https://admin-bot.duckdns.org")
UID = int(os.environ.get("AUDIT_UID", "5885953495"))


def init_data(user_id: int) -> str:
    data = {
        "auth_date": str(int(time.time())),
        "query_id": "AAaudit",
        "user": json.dumps({"id": user_id, "first_name": "Audit"},
                           separators=(",", ":")),
    }
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", settings.API_TOKEN.encode(),
                      hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


INIT = init_data(UID)


def get(path: str, chat_id=None, timeout: int = 20):
    req = urllib.request.Request(BASE + path, method="GET")
    req.add_header("X-Telegram-Init-Data", INIT)
    if chat_id is not None:
        req.add_header("X-Chat-Id", str(chat_id))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return {"status": resp.status, "json": json.loads(raw)}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")[:300]
        return {"status": exc.code, "body": body}
    except Exception as exc:                       # noqa: BLE001
        return {"status": None, "error": f"{type(exc).__name__}: {exc}"}


def main() -> int:
    out: dict = {"base": BASE, "uid": UID, "checks": {}}
    out["checks"]["healthz"] = get("/healthz")
    out["checks"]["me"] = get("/api/me")

    expr = get("/api/speech/expression")
    out["checks"]["expression_global"] = expr
    if expr.get("status") == 200:
        j = expr["json"]
        out["expression_global_view"] = {
            "present": j.get("present"), "inheritance": j.get("inheritance"),
            "global_present": j.get("global_present"),
            "chat_present": j.get("chat_present"),
            "values": j.get("values"), "note": (j.get("note") or "")[:120],
            "rendered_text": (j.get("rendered_text") or "")[:400],
            "document": j.get("document"),
            "can_edit": j.get("can_edit"), "scope": j.get("scope"),
        }

    style = get("/api/speech/style")
    if style.get("status") == 200:
        j = style["json"]
        out["style_global_view"] = {
            "source": j.get("source"), "revision": j.get("revision"),
            "rules": len(j.get("rules") or []),
            "soft": len(j.get("soft_instructions") or []),
            "document": j.get("document"), "can_edit": j.get("can_edit"),
            "rules_ids": [r.get("id") for r in (j.get("rules") or [])][:12],
        }

    core = get("/api/speech/core")
    if core.get("status") == 200:
        j = core["json"]
        out["core_global_view"] = {
            "inheritance": j.get("inheritance"),
            "global_present": j.get("global_present"),
            "document": j.get("document"),
            "selection": j.get("selection"),
            "editions": {k: {kk: v.get(kk) for kk in
                             ("source", "revision", "chars", "withheld",
                              "differs_from_factory")}
                         for k, v in (j.get("editions") or {}).items()},
            "history_rows": len(j.get("history") or []),
            "can_edit": j.get("can_edit"),
        }

    ov = get("/api/speech/overview")
    if ov.get("status") == 200:
        j = ov["json"]
        out["overview_global_view"] = {
            "scope": j.get("scope"), "chat_id": j.get("chat_id"),
            "cards": [c.get("id") for c in (j.get("cards") or [])],
        }

    out["checks"]["expression_chat"] = get("/api/speech/expression",
                                           chat_id=int(os.environ.get(
                                               "AUDIT_CHAT", "-1001234567890")))
    acc = get("/api/access/chats")
    if acc.get("status") == 200:
        out["access_chats"] = acc["json"]

    with open(os.path.join(os.path.dirname(__file__),
                           "probe_live_readonly.json"), "w",
              encoding="utf-8") as fh:
        json.dump(out, fh, ensure_ascii=False, indent=2)
    print(json.dumps(out, ensure_ascii=False, indent=2)[:6000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
