import json
from pathlib import Path

run = Path(r"C:\Users\main\.config\opencode\WorkspaceData\runs\c742e4de9e92c489\self-diag-01-0ccfa8fbf52b\probe-5da2b593e3")
before = json.loads((run / "parity-before" / "raw.json").read_text(encoding="utf-8"))
after = json.loads((run / "parity-after" / "raw.json").read_text(encoding="utf-8"))


def index(items):
    out = {}
    for it in items:
        key = it.get("key") or it.get("pg_key") or it.get("id") or it.get("path")
        out[key] = it
    return out


result = {}
for surface in ("config_global", "config_chat_-1004482340693", "config_chat_-1002661910336"):
    b = index(before[surface]["items"])
    a = index(after[surface]["items"])
    added = sorted(set(a) - set(b))
    removed = sorted(set(b) - set(a))
    changed = []
    for key in set(a) & set(b):
        x, y = json.loads(json.dumps(b[key], sort_keys=True)), json.loads(json.dumps(a[key], sort_keys=True))
        if x != y:
            changed.append(key)
    result[surface] = {"added": added, "removed": removed, "changed": sorted(changed),
                       "before": len(b), "after": len(a)}
    for key in added:
        it = a[key]
        result[surface]["added_item_%s" % key] = {
            "pg_id": it.get("pg_id"), "group": it.get("group"), "type": it.get("type"),
            "value": it.get("value"), "description": (it.get("description") or "")[:160],
        }

print(json.dumps(result, ensure_ascii=False, indent=1)[:4000])
(run / "parity-items-diff.json").write_text(json.dumps(result, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
