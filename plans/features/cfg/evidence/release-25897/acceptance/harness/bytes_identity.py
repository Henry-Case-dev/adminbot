# -*- coding: utf-8 -*-
"""Resolve which served CSS/HTML bytes correspond to the candidate files."""
from __future__ import annotations

import hashlib
import json
import pathlib
import sys

import httpx

BASE = "https://admin-bot.duckdns.org"
REPO = pathlib.Path(r"C:\Code\Python\adminbot")


def sha12(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:12]


def main() -> int:
    out = {"repo": {}, "served": {}}
    for rel in ("web/static/app.css", "web/app.js", "web/index.html"):
        data = (REPO / rel).read_bytes()
        out["repo"][rel] = {"bytes": len(data), "sha256_12": sha12(data)}
    with httpx.Client(base_url=BASE, timeout=30.0) as c:
        for path in ("/static/app.css", "/static/app.css?v=2.58.97",
                     "/web/static/app.css", "/web/app.js",
                     "/web/app.js?v=2.58.97", "/web/index.html", "/web/"):
            r = c.get(path)
            out["served"][path] = {"http": r.status_code,
                                   "bytes": len(r.content),
                                   "sha256_12": sha12(r.content),
                                   "first_line": r.content.decode(
                                       "utf-8", "replace").splitlines()[0][:120]
                                   if r.content else ""}
    print(json.dumps(out, ensure_ascii=False, indent=1))
    pathlib.Path(sys.argv[1]).write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
