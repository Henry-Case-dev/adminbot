import json
from pathlib import Path

import live_258197 as H

DEPLOY_TS = 1794476497  # 2026-11-12T09:41:37Z

out = {}
for chat in (H.CHAT_A, H.CHAT_B):
    st, raw, body = H.get("/api/config", chat)
    st2, raw2, body2 = H.get("/api/config", chat)
    diffs = []

    def walk(a, b, path=""):
        if type(a) is not type(b):
            diffs.append(path + ":type")
        elif isinstance(a, dict):
            for k in sorted(set(a) | set(b)):
                if k not in a or k not in b:
                    diffs.append(path + "/" + k + ":missing")
                else:
                    walk(a[k], b[k], path + "/" + k)
        elif isinstance(a, list):
            if len(a) != len(b):
                diffs.append(path + ":len")
            for i, (x, y) in enumerate(zip(a, b)):
                walk(x, y, path + "/%d" % i)
        else:
            if a != b:
                diffs.append(path + ":value")

    walk(body, body2)
    stamps = []

    def scan(obj, path=""):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k in ("updated_at", "chat_updated_at") and isinstance(v, str):
                    stamps.append((path + "/" + k, v))
                scan(v, path + "/" + k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj[:8]):
                scan(v, path + "/%d" % i)

    scan(body)
    out[str(chat)] = {
        "http": [st, st2],
        "diff_two_calls": diffs[:10],
        "response_updated_at": body.get("updated_at"),
        "latest_item_stamp": max((s[1] for s in stamps), default=None),
        "items": len(body.get("items") or []),
    }
print(json.dumps(out, ensure_ascii=False, indent=1))
Path("chat-config-stability-2.58.197.json").write_text(
    json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
