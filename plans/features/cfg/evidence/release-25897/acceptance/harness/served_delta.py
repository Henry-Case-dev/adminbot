# -*- coding: utf-8 -*-
"""Explain the served-vs-repo byte delta for `/static/app.css` and /web/."""
from __future__ import annotations

import difflib
import json
import pathlib
import sys

import httpx

BASE = "https://admin-bot.duckdns.org"
REPO = pathlib.Path(r"C:\Code\Python\adminbot")


def main() -> int:
    repo_css = (REPO / "web/static/app.css").read_text(encoding="utf-8")
    with httpx.Client(base_url=BASE, timeout=30.0) as c:
        served_css = c.get("/static/app.css").content.decode("utf-8")
        repo_html = (REPO / "web/index.html").read_text(encoding="utf-8")
        served_html = c.get("/web/").content.decode("utf-8")
    out = {}
    for name, a, b in (("css", repo_css, served_css),
                       ("html", repo_html, served_html)):
        al, bl = a.splitlines(), b.splitlines()
        diff = [d for d in difflib.unified_diff(al, bl, n=0, lineterm="")
                if d[:1] in "+-" and not d.startswith(("+++", "---"))]
        out[name] = {"repo_lines": len(al), "served_lines": len(bl),
                     "diff_count": len(diff),
                     "diff_sample": diff[:12]}
    print(json.dumps(out, ensure_ascii=False, indent=1)[:4000])
    pathlib.Path(sys.argv[1]).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
