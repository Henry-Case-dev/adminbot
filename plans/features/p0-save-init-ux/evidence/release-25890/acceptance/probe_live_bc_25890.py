# -*- coding: utf-8 -*-
"""ACCEPTANCE-90 — B/C live-диагностика 2.58.90 через HTTPS API админки.

Лейн ACCEPTANCE-90. Только GET (режим `read`) либо явное включение
per-chat гейта nostalgia для PET-чата (режим `enable-gate`; штатный PUT,
обратимо, назначение — PET-релиз по правилу проекта).

Запуск:
    python probe_live_bc_25890.py read
    python probe_live_bc_25890.py enable-gate

Результат: acceptance-bc-25890.json рядом со скриптом.
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
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from config.settings import settings          # noqa: E402

BASE = "https://admin-bot.duckdns.org"
UID = 5885953495
WORK = -1002661910336                         # рабочий чат (nostalgia: on)
PET = -1004482340693                          # PET-чат (nostalgia: off → on)
OUT = os.path.join(os.path.dirname(__file__), "acceptance-bc-25890.json")
REPORT: dict = {"probe": "acceptance-bc-25890", "lane": "ACCEPTANCE-90",
                "t0_utc": "2026-10-18T13:34:23Z",
                "chats": {"work": WORK, "pet": PET}, "steps": []}


def out_path(mode: str) -> str:
    return os.path.join(os.path.dirname(__file__),
                        "acceptance-bc-25890-%s.json" % mode)


def init_data() -> str:
    data = {"auth_date": str(int(time.time())),
            "user": json.dumps({"id": UID, "first_name": "Acc90"},
                               separators=(",", ":"))}
    check = "\n".join(f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", settings.API_TOKEN.encode(),
                      hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urlencode(data)


def req(method: str, path: str, *, chat=None, body=None, timeout: float = 40):
    headers = {"X-Telegram-Init-Data": init_data()}
    data = None
    if chat is not None:
        headers["X-Chat-Id"] = str(chat)
    if body is not None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = urllib.request.Request(BASE + path, data=data, method=method,
                                     headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8", "replace")
            try:
                return {"status": resp.status, "json": json.loads(raw)}
            except ValueError:
                return {"status": resp.status, "json": {"_raw": raw[:300]}}
    except urllib.error.HTTPError as exc:
        txt = exc.read().decode("utf-8", "replace")
        try:
            payload = json.loads(txt)
        except ValueError:
            payload = {"_raw": txt[:300]}
        return {"status": exc.code, "json": payload}
    except Exception as exc:                                  # noqa: BLE001
        return {"status": None, "error": f"{type(exc).__name__}: {exc}"}


def step(sid: str, ok: bool, detail: dict) -> bool:
    REPORT["steps"].append({"id": sid, "ok": bool(ok), "detail": detail})
    print("[%s] %s | %s" % (sid, "PASS" if ok else "FAIL",
                            json.dumps(detail, ensure_ascii=False)[:700]),
          flush=True)
    return bool(ok)


def funnels(chat=None) -> dict:
    path = "/api/memory/intel-funnels" + (
        "?chat_id=%d" % chat if chat is not None else "")
    return req("GET", path)


def read_all() -> None:
    f_glob = funnels()
    f_work = funnels(WORK)
    REPORT["funnels_global"] = f_glob
    REPORT["funnels_work"] = f_work
    init = ((f_glob.get("json") or {}).get("initiative") or {})
    counters = (init.get("job") or {}).get("counters") or {}
    events = (init.get("events") or {}).get("24h") or {}
    live = init.get("liveness") or {}
    step("C1_initiative_job_scan_anchored",
         int(counters.get("scan_anchored") or 0) >= 1,
         {"scan_anchored": counters.get("scan_anchored"),
          "passes": counters.get("passes"), "observed": counters.get("observed"),
          "opportunities": counters.get("opportunities"),
          "evals": counters.get("evals"),
          "cursor": counters.get("cursor") or counters.get("last_id"),
          "job_status": (init.get("job") or {}).get("status"),
          "job_finished_at": (init.get("job") or {}).get("finished_at"),
          "liveness": live})
    step("C2_initiative_scan_events",
         int(events.get("initiative_observer_scan") or 0) >= 1,
         {"events_24h": events})
    vit_work = req("GET", "/api/memory/initiative-vitality?chat_id=%d&hours=24"
                   % WORK)
    REPORT["vitality_work"] = vit_work
    vj = vit_work.get("json") or {}
    decisions = vj.get("decisions") or []
    refusals = vj.get("refusals") or []
    stages = sorted({str(d.get("stage") or "") for d in decisions
                     if d.get("stage")})
    codes = sorted({str(d.get("reason_code") or "") for d in decisions})
    step("C3_initiative_decisions_reason_codes",
         bool(decisions) or bool(refusals),
         {"decisions": decisions[:5], "refusals": refusals[:3],
          "decision_stages": stages, "reason_codes": codes,
          "activity": vj.get("activity"), "gates": vj.get("gates"),
          "scope": vj.get("scope"), "sends": len(vj.get("sends") or [])})
    vit_pet = req("GET", "/api/memory/initiative-vitality?chat_id=%d&hours=24"
                  % PET)
    REPORT["vitality_pet"] = vit_pet
    nlog_work = req("GET", "/api/memory/nostalgia/log?chat_id=%d&limit=10"
                    % WORK)
    REPORT["nostalgia_log_work"] = nlog_work
    nlog_pet = req("GET", "/api/memory/nostalgia/log?chat_id=%d&limit=10"
                   % PET)
    REPORT["nostalgia_log_pet"] = nlog_pet
    rows_w = nlog_work.get("json") or []
    rows_p = nlog_pet.get("json") or []
    step("B1_nostalgia_log_rows", True,
         {"work_rows": len(rows_w), "work_head": rows_w[:3],
          "pet_rows": len(rows_p), "pet_head": rows_p[:2],
          "status": nlog_work.get("status")})
    cog_w = req("GET", "/api/memory/cognition/status?chat_id=%d" % WORK)
    cog_p = req("GET", "/api/memory/cognition/status?chat_id=%d" % PET)
    REPORT["cognition_work"] = cog_w
    REPORT["cognition_pet"] = cog_p
    sw = (cog_w.get("json") or {})
    sp = (cog_p.get("json") or {})
    step("B2_nostalgia_scenario_state", True,
         {"work": {k: sw.get(k) for k in ("nostalgia", "enabled")},
          "pet": {k: sp.get(k) for k in ("nostalgia", "enabled")},
          "work_enabled": sw.get("enabled"), "pet_enabled": sp.get("enabled")})
    gates_work = req("GET", "/api/chat/%d/gates" % WORK)
    gates_pet = req("GET", "/api/chat/%d/gates" % PET)
    REPORT["gates_work"] = gates_work
    REPORT["gates_pet"] = gates_pet
    g = (gates_pet.get("json") or {})
    step("B3_pet_gate_state", True,
         {"pet_nostalgia": (g.get("gates") or {}).get("nostalgia"),
          "pet_updated_at": g.get("updated_at"),
          "work_nostalgia": ((gates_work.get("json") or {}).get("gates")
                             or {}).get("nostalgia")})


def enable_pet_gate() -> None:
    cur = (req("GET", "/api/chat/%d/gates" % PET).get("json") or {})
    was = (cur.get("gates") or {}).get("nostalgia")
    if was:
        step("G1_pet_gate_already_on", True, {"nostalgia": was})
    else:
        put = req("PUT", "/api/chat/%d/gates" % PET,
                  body={"feature": "nostalgia", "enabled": True})
        after = (req("GET", "/api/chat/%d/gates" % PET).get("json") or {})
        step("G1_pet_gate_enable",
             put.get("status") == 200
             and bool((after.get("gates") or {}).get("nostalgia")),
             {"put_status": put.get("status"),
              "put_body": put.get("json"),
              "nostalgia_after": (after.get("gates") or {}).get("nostalgia"),
              "updated_at_before": cur.get("updated_at"),
              "updated_at_after": after.get("updated_at")})
    work = (req("GET", "/api/chat/%d/gates" % WORK).get("json") or {})
    step("G2_work_gate_untouched",
         bool((work.get("gates") or {}).get("nostalgia")),
         {"work_nostalgia": (work.get("gates") or {}).get("nostalgia")})


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "read"
    REPORT["mode"] = mode
    REPORT["now_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    health = req("GET", "/healthz")
    REPORT["prod_health"] = health.get("json") or health
    print("[env] %s" % json.dumps(REPORT["prod_health"], ensure_ascii=False))
    if mode == "enable-gate":
        enable_pet_gate()
    else:
        read_all()
    REPORT["finished_utc"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    dest = out_path(mode)
    with open(dest, "w", encoding="utf-8") as fh:
        json.dump(REPORT, fh, ensure_ascii=False, indent=2)
    print("[done] -> %s" % dest)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
