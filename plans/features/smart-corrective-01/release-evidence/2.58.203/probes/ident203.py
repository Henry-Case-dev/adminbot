# -*- coding: utf-8 -*-
"""Deployed identity through the deployed service (read-only)."""
from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path

APP = "/var/www/admin_bot"
sys.path.insert(0, APP)

for line in Path(APP, ".env").read_text().splitlines():
    line = line.strip()
    if not line or line.startswith("#") or "=" not in line:
        continue
    k, v = line.split("=", 1)
    os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


async def main() -> dict:
    import subprocess

    from services import deploy_identity
    raw = subprocess.run(
        ["systemctl", "show", "admin_bot", "-p", "ExecMainStartTimestamp",
         "--value"], capture_output=True, text=True, timeout=20).stdout.strip()
    iso = ""
    if raw:
        core = raw.split(" UTC")[0].split()
        if len(core) >= 3:
            iso = f"{core[-2]}T{core[-1]}Z"
    fn = getattr(deploy_identity, "collect_identity")
    result = fn(APP, process_started_at=iso or None)
    if asyncio.iscoroutine(result):
        result = await result
    if hasattr(result, "as_dict"):
        result = result.as_dict()
    if isinstance(result, dict):
        result["_process_started_at_source"] = {"raw": raw, "iso": iso}
    return result


if __name__ == "__main__":
    data = asyncio.run(main())
    dest = sys.argv[1] if len(sys.argv) > 1 else "/tmp/identity203.json"
    Path(dest).write_text(json.dumps(data, ensure_ascii=False, indent=1,
                                     default=str), encoding="utf-8")
    keep = ("code", "reason", "deployed_sha", "checkout_sha", "dirty",
            "local_source_verification", "process_started_at", "deployed_at",
            "version_provenance", "previous_sha", "previous_version",
            "upstream_head", "sources", "conflict", "schema", "repo_origin")
    print(json.dumps({k: data.get(k) for k in keep if k in data},
                     ensure_ascii=False, indent=1, default=str))
