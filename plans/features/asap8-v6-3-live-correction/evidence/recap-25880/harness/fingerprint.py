"""RECAP-25880 — fingerprint of the captured candidate (worktree @ deployed)."""
import hashlib
import json
import os
import subprocess

WT = r"C:\Users\main\.config\opencode\OpenCodeScratch\adminbot-ccef72c25768\recap-31c16555"
OUT = r"C:\Code\Python\adminbot\plans\features\asap8-v6-3-live-correction\evidence\recap-25880"

EXPECTED = {
    "web/static/app.css": "70975eb2eac08f01beaecc1bf5be6ff005de75efada145f96785c0973c887be2",
    "web/app.js": "9774da6a4e932287123cc49f8c84337a77f2bdef63385b3e76a9d47d5f9cb8ac",
    "web/index.html": "e209d5faf7e8e54a907a35c570aba9f574cbfa9fbae2ae1fc8c95e53be26b3e0",
    "services/param_catalog.py": "1981d3382e2ee81222107027ead5e7e61ef438cbdc91afcd1c13e668d0d15ba7",
    "config/settings.py": "5a31a2770ab27ba8b21f3f1fba499c50464b7798af15be8b79c09a31b9f722fd",
}


def sha256(path):
    with open(path, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()


def main():
    head = subprocess.run(["git", "-C", WT, "rev-parse", "HEAD"],
                          capture_output=True, text=True, check=True).stdout.strip()
    status = subprocess.run(["git", "-C", WT, "status", "--porcelain", "--",
                             "web", "services/param_catalog.py", "config/settings.py"],
                            capture_output=True, text=True, check=True).stdout.strip()
    files = {}
    for rel, exp in EXPECTED.items():
        got = sha256(os.path.join(WT, rel))
        files[rel] = {"sha256": got, "expected_deployed": exp, "match": got == exp}
    out = {"worktree": WT, "head": head,
           "head_expected": "31c165556dbe8c289606bd6bee1af49bb72d5794",
           "head_match": head == "31c165556dbe8c289606bd6bee1af49bb72d5794",
           "code_paths_dirty": status if status else None,
           "files": files,
           "all_match": all(v["match"] for v in files.values())}
    with open(os.path.join(OUT, "fingerprint.json"), "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(out, ensure_ascii=False, indent=1))
    return 0 if out["all_match"] and out["head_match"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
