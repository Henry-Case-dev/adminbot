# -*- coding: utf-8 -*-
"""Live RBAC probe on deployed 2.58.198: diagnostic policy matrix + protected paths.

Owner vs non-admin member (read-only GETs; no messages, no writes).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(r"C:\Code\Python\adminbot\plans\features\self-diag-01\release-258198\harness")))
import live_258198 as H  # noqa: E402

OUT = Path(sys.argv[1])


def get(path: str, init: str, chat: int | None = H.CHAT_A):
    return H.get(path, chat_id=chat, init=init)


def summarize_matrix(body: dict) -> dict:
    items = body.get("items") or {}
    out = {}
    if isinstance(items, list):
        items = {str(it): {} for it in items}
    for cap, it in items.items():
        if cap in ("bot_server_state", "prompts", "source_code", "logs_traceback",
                   "detailed_metrics"):
            out[cap] = {
                "data_class": it.get("data_class"),
                "configurable": it.get("configurable"),
                "effective": it.get("effective"),
                "source": it.get("source"),
                "hard_rules": it.get("hard_rules"),
            }
    return out


def main() -> int:
    result: dict = {"release": "2.58.198"}
    st, raw, body = get("/api/access/diagnostic_policy", H.INIT)
    result["matrix_owner"] = {"http": st, "roles": (body or {}).get("roles"),
                              "caps": summarize_matrix(body or {}),
                              "items": len((body or {}).get("items") or [])}
    st, raw, body = get("/api/access/diagnostic_policy", H.INIT_KOSTIK)
    result["matrix_nonadmin"] = {"http": st, "roles": (body or {}).get("roles"),
                                 "caps": summarize_matrix(body or {}),
                                 "items": len((body or {}).get("items") or []),
                                 "restricted": (body or {}).get("restricted")}

    probes = {}
    for name, path in (
            ("prompts_catalog", "/api/prompts/catalog"),
            ("prompt_versions", "/api/prompts/prompts.meme_joke/versions"),
            ("self_diagnosis", "/api/status/self-diagnosis"),
            ("status", "/api/status"),
            ("speech_inspector_miss", "/api/speech/inspector?correlation_id=nope"),
    ):
        st_o, _raw, body_o = get(path, H.INIT)
        st_n, _raw, body_n = get(path, H.INIT_KOSTIK)
        probes[name] = {
            "owner_http": st_o,
            "nonadmin_http": st_n,
            "nonadmin_detail": (body_n or {}).get("detail") if isinstance(body_n, dict) else None,
            "nonadmin_keys": sorted((body_n or {}).keys())[:8] if isinstance(body_n, dict) else None,
        }
    result["protected_paths"] = probes
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "live-rbac-2.58.198.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=1)[:4000])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
