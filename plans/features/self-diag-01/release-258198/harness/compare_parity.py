# -*- coding: utf-8 -*-
"""Effective-config parity: deep diff of the raw before/after surface snapshots.

Usage: compare_parity.py before_dir after_dir out.json
Reports every differing leaf path, marks the volatile ones (server-observed
timestamps / pid / uptime) which cannot be stable across two samples, and
fails only when a stable (owner-visible) value differs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

VOLATILE_KEYS = {
    "observed_at", "generated_at", "uptime_seconds", "pid", "last_tick_ts",
    "now", "checked_at", "sampled_at", "server_time",
}
MAX_LISTED = 200


def walk(before, after, path, out):
    if len(out) >= MAX_LISTED:
        return
    if type(before) is not type(after):
        out.append({"path": path, "kind": "type", "before": repr(before)[:80],
                    "after": repr(after)[:80]})
        return
    if isinstance(before, dict):
        for key in sorted(set(before) | set(after)):
            if key not in before:
                out.append({"path": "%s.%s" % (path, key), "kind": "added",
                            "after": repr(after[key])[:80]})
            elif key not in after:
                out.append({"path": "%s.%s" % (path, key), "kind": "removed",
                            "before": repr(before[key])[:80]})
            else:
                walk(before[key], after[key], "%s.%s" % (path, key), out)
        return
    if isinstance(before, list):
        if len(before) != len(after):
            out.append({"path": path, "kind": "length", "before": len(before),
                        "after": len(after)})
            return
        for i, (b, a) in enumerate(zip(before, after)):
            walk(b, a, "%s[%d]" % (path, i), out)
        return
    if before != after:
        out.append({"path": path, "kind": "value", "before": repr(before)[:80],
                    "after": repr(after)[:80]})


def is_volatile(path: str) -> bool:
    leaf = path.rsplit(".", 1)[-1]
    return leaf in VOLATILE_KEYS


def main() -> int:
    before_dir, after_dir, out_path = Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])
    before = json.loads((before_dir / "raw.json").read_text(encoding="utf-8"))
    after = json.loads((after_dir / "raw.json").read_text(encoding="utf-8"))
    result = {"surfaces": {}, "stable_diffs": 0, "volatile_diffs": 0}
    for name in sorted(set(before) | set(after)):
        if name not in before or name not in after:
            result["surfaces"][name] = {"present": [name in before, name in after]}
            result["stable_diffs"] += 1
            continue
        diffs: list = []
        walk(before[name], after[name], name, diffs)
        stable = [d for d in diffs if not is_volatile(d["path"])]
        volatile = [d for d in diffs if is_volatile(d["path"])]
        result["surfaces"][name] = {
            "identical": not diffs,
            "diff_count": len(diffs),
            "stable": stable,
            "volatile_paths": sorted({d["path"].rsplit(".", 1)[-1] for d in volatile}),
            "volatile_count": len(volatile),
        }
        result["stable_diffs"] += len(stable)
        result["volatile_diffs"] += len(volatile)
    result["verdict"] = "PARITY_OK" if result["stable_diffs"] == 0 else "PARITY_DIFF"
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "surfaces"},
                     ensure_ascii=False))
    for name, info in result["surfaces"].items():
        print("%-42s diffs=%s stable=%d volatile=%d %s" % (
            name, info.get("diff_count"), len(info.get("stable") or []),
            info.get("volatile_count", 0), info.get("volatile_paths") or ""))
        for d in (info.get("stable") or [])[:10]:
            print("    STABLE:", d)
    return 0 if result["stable_diffs"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
