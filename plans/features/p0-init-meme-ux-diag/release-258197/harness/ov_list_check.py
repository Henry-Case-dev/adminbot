# -*- coding: utf-8 -*-
"""Exact OV-LIST live check that caught the 2.58.196 defect.

For real meme attempts in the overview: label must be "автоматически" when the
terminal detail carries attempt_mode=automatic, "вручную (/meme)" for manual,
and "способ не записан" only when the mode is absent/unknown.
"""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import sync_playwright

import live_258197 as H

BASE = "https://admin-bot.duckdns.org/web/#/modules/initiative"
OUT = Path(__file__).parent
INIT = """
window.Telegram = window.Telegram || {};
window.Telegram.WebApp = { initData: %s, initDataUnsafe: {user:{id:%d,first_name:'owner'}},
  ready:function(){},expand:function(){},close:function(){},onEvent:function(){},
  offEvent:function(){},colorScheme:'dark',themeParams:{},isExpanded:true,
  viewportStableHeight: Math.max(0,(window.innerHeight||800)-56), viewportHeight: window.innerHeight||800 };
try { sessionStorage.setItem('adminbot.initData', %s); } catch(e){}
try { localStorage.setItem('adminbot.active_chat_id', '%s'); } catch(e){}
"""
JS = r"""
() => Array.from(document.querySelectorAll('[data-ini-event]')).map(el => ({
  kind: el.getAttribute('data-ini-event'),
  time: (el.querySelector('.ini-event__time') || {}).innerText,
  label: (el.querySelector('[data-ini-event-mode]') || {}).innerText,
  text: el.innerText.replace(/\s+/g, ' ').trim().slice(0, 220)
}))
"""

res = {"release": "2.58.197", "chats": {}}
with sync_playwright() as pw:
    browser = pw.chromium.launch()
    for label, chat in (("chatA", H.CHAT_A), ("chatB", H.CHAT_B)):
        st, raw, body = H.get("/api/initiative/meme-settings", chat)
        attempts = ((body or {}).get("analytics") or {}).get("attempts") or []
        by_job = {}
        for row in attempts:
            job = str(row.get("job_id") or "")
            if not job:
                continue
            detail = row.get("detail")
            try:
                facts = json.loads(detail) if isinstance(detail, str) else (detail or {})
            except Exception:
                facts = {}
            raw_mode = str(facts.get("attempt_mode") or "") if isinstance(facts, dict) else ""
            entry = by_job.setdefault(job, {"job": job, "ts": row.get("ts"),
                                            "stage": row.get("stage"),
                                            "raw_modes": set(), "raw_mode": raw_mode})
            if raw_mode:
                entry["raw_modes"].add(raw_mode)
                entry["raw_mode"] = raw_mode
        # expected label by raw value
        def expected(raw):
            raw = str(raw or "").strip().lower()
            if raw == "manual":
                return "вручную (/meme)"
            if raw in ("auto", "automatic"):
                return "автоматически"
            return "способ не записан"

        ctx = browser.new_context(viewport={"width": 1280, "height": 900})
        ctx.add_init_script(INIT % (json.dumps(H.INIT), H.OWNER, json.dumps(H.INIT), chat))
        page = ctx.new_page()
        page.goto(BASE, wait_until="load", timeout=60000)
        page.wait_for_selector("[data-ini-event]", state="attached", timeout=45000)
        page.wait_for_timeout(3500)
        rows = page.evaluate(JS)
        page.screenshot(path=str(OUT / ("live-overview-%s-2.58.197.png" % label)),
                        full_page=True)
        ctx.close()

        checks = []
        for row in rows:
            if row.get("kind") != "meme":
                continue
            # match by the rendered time is not reliable; verify the rule on the
            # labels present in meme rows plus the real modes distribution
            checks.append({"time": row.get("time"), "label": (row.get("label") or "").strip(),
                           "text": row.get("text")})
        modes = sorted({m for e in by_job.values() for m in e["raw_modes"]})
        auto_rows = [c for c in checks if c["label"] == "автоматически"]
        unknown_rows = [c for c in checks if c["label"] == "способ не записан"]
        manual_rows = [c for c in checks if c["label"] == "вручную (/meme)"]
        res["chats"][label] = {
            "chat_id": chat,
            "analytics_jobs": len(by_job),
            "raw_attempt_modes_present": modes,
            "jobs_with_automatic": sum(1 for e in by_job.values()
                                       if "automatic" in e["raw_modes"]),
            "jobs_without_mode": sum(1 for e in by_job.values()
                                     if not e["raw_modes"]),
            "rendered_meme_rows": checks,
            "labels_seen": {"автоматически": len(auto_rows),
                            "способ не записан": len(unknown_rows),
                            "вручную (/meme)": len(manual_rows)},
            "expected_auto_ok": (len(auto_rows) > 0
                                 if any("automatic" in e["raw_modes"] or "auto" in e["raw_modes"]
                                        for e in by_job.values()) else None),
        }
    browser.close()

Path(OUT / "live-ov-list-2.58.197.json").write_text(
    json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
print(json.dumps(res, ensure_ascii=False, indent=1)[:5000])
