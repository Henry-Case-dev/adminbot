# -*- coding: utf-8 -*-
"""ACCEPTANCE-91 final focused factcheck: explicit request + registered target.

Combines the two pieces that were missing separately:
  * the explicit "проверь факт" phrasing (planner selects fact_check);
  * a real smart_messages row for the trigger (envelope target resolves).
No image generation.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
import time

APP = "/var/www/admin_bot"
os.chdir(APP)
sys.path.insert(0, APP)
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

WORK_CHAT = -1002661910336
SYNTH_USER = 990002001


def load_live():
    spec = importlib.util.spec_from_file_location(
        "accept91_live", "/tmp/accept91_live.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


async def main() -> int:
    mod = load_live()
    await mod.bootstrap()
    mod.CTX.api = mod.Api()
    res = {"scenario": "4-factcheck-registered", "turns": []}
    anchor = await mod.CTX.rec.send_message(
        WORK_CHAT,
        "🧪 Приёмка 2.58.91 · factcheck explicit+registered (контроль).")
    mid = int(anchor.message_id)
    q = "бот, проверь факт: вода закипает при 100 °C на уровне моря."
    try:
        try:
            await mod.sqlite_exec(
                "DELETE FROM smart_messages WHERE chat_id=? AND tg_message_id=?",
                (WORK_CHAT, mid))
        except Exception:
            pass
        row_id = await mod.CTX.db.save_smart_message(
            SYNTH_USER, WORK_CHAT, q, mid, int(time.time()), "text",
            "Acceptance", message_id=mid, origin_type="user")
        res["smart_message_row"] = row_id
    except Exception as exc:  # noqa: BLE001
        res["smart_message_error"] = "%s: %s" % (type(exc).__name__,
                                                 str(exc)[:160])
    t = await mod.run_turn(q, msg_id=mid, reply_to=anchor,
                           label="fact-registered", timeout=300)
    res["turns"].append({"phrase": q, **mod._strip_turn(t)})
    res["tool_called"] = mod._turn_has_tool(t, "fact_check")
    res["plan_caps"] = mod._turn_plan_caps(t)
    res["tool_result"] = next(
        (x for x in t.get("tool_calls", []) if x.get("tool") == "fact_check"),
        None)
    res["ok"] = res["tool_called"]
    mod.save("scenario-4-factcheck-registered.json", res)
    print("AC91R FACT_REG | tool=%s caps=%s result=%s"
          % (res["tool_called"], res["plan_caps"],
             json.dumps(res.get("tool_result") or {},
                        ensure_ascii=False)[:500]), flush=True)
    return 0


if __name__ == "__main__":
    rc = 4
    try:
        rc = asyncio.run(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        print("AC91R FATAL | %s: %s" % (type(exc).__name__,
                                        str(exc)[:300]), flush=True)
        traceback.print_exc()
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass
    print("AC91R RC=%d" % rc, flush=True)
    os._exit(rc)
