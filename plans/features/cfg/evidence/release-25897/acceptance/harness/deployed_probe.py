# -*- coding: utf-8 -*-
"""Read-only probe of the DEPLOYED 2.58.97 MiniApp bytes (HTTPS, no SSH).

Writes `deployed-probe.json` with: healthz (loopback not reachable from here ->
HTTPS only), the served index.html hash, every referenced local asset hash,
CFG-04 served markers and page_ver/subst_css counts.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys
import time
import urllib.parse

import httpx

BASE = "https://admin-bot.duckdns.org"
OUT = pathlib.Path(sys.argv[1])


def sha12(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()[:12]


def main() -> int:
    out = {"now_utc": time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime()),
           "base": BASE}
    with httpx.Client(base_url=BASE, timeout=30.0,
                      headers={"User-Agent": "acceptance-97/1.0"}) as c:
        h = c.get("/healthz")
        out["healthz"] = {"http": h.status_code, "body": h.text[:200]}
        idx = c.get("/web/")
        html = idx.content
        out["web"] = {"http": idx.status_code, "bytes": len(html),
                      "sha256_12": sha12(html),
                      "content_type": idx.headers.get("content-type")}
        text = html.decode("utf-8", "replace")
        # referenced local assets
        refs = sorted(set(re.findall(r'(?:src|href)="(/[^"]+)"', text)))
        assets = {}
        for ref in refs:
            if not re.search(r"\.(js|css|png|svg|webp|woff2?)(\?|$)", ref):
                continue
            r = c.get(ref)
            assets[ref] = {"http": r.status_code, "bytes": len(r.content),
                           "sha256_12": sha12(r.content),
                           "content_type": r.headers.get("content-type")}
        out["assets"] = assets
        out["markers"] = {
            "PAGE_VER": len(re.findall(r"page-ver|PAGE_VER", text)),
            "SUBST_CSS": text.count("subst-css"),
            "STICKY_SAVE_SERVED": text.count("sticky-save"),
            "CFG04_KB_OFFSET_CSS": text.count("--kb-offset"),
            "CFG04_SAFE_AREA": text.count("tg-content-safe-area-inset-bottom"),
            "CFG04_TECH_KEY": text.count("tech-key"),
        }
        js = c.get("/web/app.js")
        jst = js.content.decode("utf-8", "replace")
        out["app_js_markers"] = {
            "sticky-save": jst.count("sticky-save"),
            "stickyDirtyCount": jst.count("stickyDirtyCount"),
            "role\": \"status": jst.count('role: "status"'),
            "Expression_Settings": jst.count("Expression_Settings"),
            "--kb-offset": jst.count("--kb-offset"),
            "tech-key": jst.count("tech-key"),
        }
        css = c.get("/static/app.css")
        ct = css.content.decode("utf-8", "replace")
        out["app_css_markers"] = {
            "sticky-save": ct.count("sticky-save"),
            "--kb-offset": ct.count("--kb-offset"),
            "safe-area-inset-bottom": ct.count("safe-area-inset-bottom"),
        }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(json.dumps({k: out[k] for k in ("healthz", "web", "markers",
                                         "app_js_markers",
                                         "app_css_markers")},
                     ensure_ascii=False, indent=1)[:2000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
