# -*- coding: utf-8 -*-
"""Build a byte-mirror of the DEPLOYED MiniApp (HTTPS) for visual inspection.

The mirror keeps the exact served bytes (including the `2.58.97` substitution)
so Browser Use renders what production serves. Hashes are recorded next to it.
"""
from __future__ import annotations

import hashlib
import json
import pathlib
import re
import sys

import httpx

BASE = "https://admin-bot.duckdns.org"
ROOT = pathlib.Path(sys.argv[1])


def sha12(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()[:12]


def main() -> int:
    out = {"base": BASE, "files": {}}
    with httpx.Client(base_url=BASE, timeout=30.0) as c:
        html = c.get("/web/").content
        (ROOT / "web").mkdir(parents=True, exist_ok=True)
        (ROOT / "web" / "index.html").write_bytes(html)
        files = {ROOT / "web" / "index.html": html}
        text = html.decode("utf-8", "replace")
        refs = sorted(set(re.findall(r'(?:src|href)="(/[^"]+)"', text)))
        for ref in refs:
            if not re.search(r"\.(js|css|png|svg|webp|woff2?)(\?|$)", ref):
                continue
            rel = ref.split("?")[0].lstrip("/")
            if rel.startswith("static/"):
                dst = ROOT / "web" / rel
            else:
                dst = ROOT / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_bytes(c.get(ref).content)
            files[dst] = None
        # app.js is the critical CFG-04 artifact
        (ROOT / "web" / "app.js").write_bytes(c.get("/web/app.js").content)
    for p in sorted(ROOT.rglob("*")):
        if p.is_file():
            data = p.read_bytes()
            out["files"][str(p.relative_to(ROOT)).replace("\\", "/")] = {
                "bytes": len(data), "sha256_12": sha12(data)}
    (ROOT / "mirror-hashes.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v["sha256_12"] for k, v in out["files"].items()},
                     ensure_ascii=False, indent=1)[:2500])
    return 0


if __name__ == "__main__":
    sys.exit(main())
