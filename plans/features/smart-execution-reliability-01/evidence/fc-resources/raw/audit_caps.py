"""S14-FC-RESOURCES audit probe: list every cap/hot-key/default used by
factcheck retrieval/decomposition, from a Git revision (no imports).

Usage: python audit_caps.py --repo <root> --rev <sha> [--json out.json]
"""
import argparse
import json
import re
import subprocess
import sys

FILES = [
    "services/factcheck_planner.py",
    "services/temporal_factcheck.py",
    "services/factcheck_service.py",
    "services/factcheck_orchestrator.py",
    "services/factcheck_suitability.py",
    "services/mca_gates.py",
    "services/param_catalog.py",
    "config/settings.py",
]

CONST_RE = re.compile(r"^([A-Z][A-Z0-9_]{2,})\s*(?::[^=]+)?=\s*(.+)$")
HOT_RE = re.compile(r"""hot\.get\(\s*["']([^"']+)["']""")
LIMIT_RE = re.compile(r"""["'](limits\.[A-Za-z0-9_.]+)["']""")
SLICE_RE = re.compile(r"\[:(\d+)\]")
SLICE_VAR_RE = re.compile(r"\[:([A-Za-z_][A-Za-z0-9_.]*)\]")
DEFAULT_RE = re.compile(r"def (\w+)\(([^)]*)\)")
CALL_RE = re.compile(r"(max_rows_per_query|max_queries|max_rows|max_evidence|budget_seconds|refine_calls)\s*[:=]\s*([^,\)\n]+)")


def git_show(repo, rev, path):
    proc = subprocess.run(["git", "-C", repo, "show", f"{rev}:{path}"],
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace")
    if proc.returncode != 0:
        return None
    return proc.stdout


def scan(repo, rev):
    result = {"rev": rev, "files": {}}
    for path in FILES:
        text = git_show(repo, rev, path)
        if text is None:
            result["files"][path] = {"missing": True}
            continue
        lines = text.splitlines()
        consts, hot, limits, slices, defaults, calls = [], [], [], [], [], []
        for i, line in enumerate(lines, 1):
            if line.strip().startswith("#"):
                continue
            m = CONST_RE.match(line)
            if m and not line.startswith((" ", "\t")):
                consts.append({"line": i, "name": m.group(1),
                               "value": m.group(2).strip()[:160]})
            for key in HOT_RE.findall(line) + LIMIT_RE.findall(line):
                hot.append({"line": i, "key": key})
            for value in SLICE_RE.findall(line):
                slices.append({"line": i, "slice": int(value),
                               "text": line.strip()[:160]})
            for value in SLICE_VAR_RE.findall(line):
                if value not in ("cap", "limit", "max_rows", "max_queries",
                                 "max_evidence", "max_fetch", "n"):
                    slices.append({"line": i, "slice": value,
                                   "text": line.strip()[:160]})
            if line.lstrip().startswith("def ") or line.lstrip().startswith("async def "):
                dm = DEFAULT_RE.search(line.strip())
                if dm and "=" in dm.group(2):
                    defaults.append({"line": i, "func": dm.group(1),
                                     "args": dm.group(2)[:220]})
            for name, value in CALL_RE.findall(line):
                calls.append({"line": i, "name": name, "value": value.strip()})
        result["files"][path] = {
            "lines": len(lines),
            "constants": consts,
            "hot_keys": hot,
            "literal_slices": slices,
            "def_defaults": defaults,
            "call_args": calls,
        }
    return result


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--rev", required=True)
    ap.add_argument("--json")
    args = ap.parse_args()
    data = scan(args.repo, args.rev)
    text = json.dumps(data, ensure_ascii=False, indent=1)
    if args.json:
        with open(args.json, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text + "\n")
    else:
        sys.stdout.write(text + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
