"""W7: проверка «полигон/стекло не тронуты» (SOUL-12.5 / SOUL-EXEC.14).

1) в диффе W7 нет ни одной строки про полигон / #lg-lens / --lg-* / aurora;
2) web/static изменён ТОЛЬКО в fullscreen-policy.js;
3) блоб полигона, блок #lg-lens и токены --lg-* совпадают с HEAD.

Запуск: .venv/Scripts/python.exe <scratch>/w7/frozen_check.py
"""
import hashlib
import io
import re
import subprocess
import sys

REPO = r"C:\Code\Python\adminbot"
FILES = ["web/index.html", "web/app.js", "web/static/fullscreen-policy.js"]
PATTERNS = [r"lg-lens", r"--lg-", r"polygon", r"#aurora", r"lgGlass",
            r"scale=.32.", r"lg-lens-map"]
FROZEN_BLOB_RE = r"data:image/[a-z]+;base64,([A-Za-z0-9+/=]{2000,})"


def run(*args):
    p = subprocess.run(list(args), cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.stdout


def sha8(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def main():
    rc = 0
    diff = run("git", "diff", "-U0", "--", *FILES)
    hits = []
    for line in diff.splitlines():
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            for pat in PATTERNS:
                if re.search(pat, line):
                    hits.append((pat, line[:160]))
    print("[frozen] подозрительные строки диффа:", len(hits))
    for pat, line in hits:
        print("   ", pat, "|", line)
    if hits:
        rc = 1

    stat = run("git", "diff", "--numstat", "--", "web/static/").strip()
    print("[frozen] git diff --numstat web/static/:\n   ", stat.replace("\n", "\n    "))
    if "fullscreen-policy.js" not in stat or "\n" in stat.strip():
        rc = 1

    for rel in ("web/index.html", "web/static/app.css", "web/app.js"):
        head = run("git", "show", "HEAD:" + rel)
        work = io.open(REPO + "\\" + rel.replace("/", "\\"), encoding="utf-8",
                       newline="").read().replace("\r\n", "\n")
        head_n = head.replace("\r\n", "\n")
        if rel == "web/index.html":
            hb = [hashlib.sha256(m.encode()).hexdigest()[:8]
                  for m in re.findall(FROZEN_BLOB_RE, head_n)]
            wb = [hashlib.sha256(m.encode()).hexdigest()[:8]
                  for m in re.findall(FROZEN_BLOB_RE, work)]
            ok = hb == wb
            print("[frozen] %s polygon blobs HEAD=%s WORK=%s -> %s"
                  % (rel, hb, wb, "SAME" if ok else "DIFF"))
            rc = rc or (0 if ok else 1)
            print("[frozen] %s scale=32: HEAD=%d WORK=%d ; lg-lens refs: HEAD=%d WORK=%d"
                  % (rel, head_n.count('scale="32"'), work.count('scale="32"'),
                     head_n.count("lg-lens"), work.count("lg-lens")))
        for name, anchor, span in (("lens", "#lg-lens", 1500),
                                   ("tokens", "--lg-", 3000)):
            i, j = head_n.find(anchor), work.find(anchor)
            if i < 0 and j < 0:
                print("[frozen] %s %s: токена нет ни в HEAD, ни в worktree "
                      "(не изменён)" % (rel, name))
                continue
            same = (i >= 0 and j >= 0
                    and sha8(head_n[i:i + span]) == sha8(work[j:j + span]))
            print("[frozen] %s %s block HEAD=%s WORK=%s -> %s"
                  % (rel, name, sha8(head_n[i:i + span]) if i >= 0 else "n/a",
                     sha8(work[j:j + span]) if j >= 0 else "n/a",
                     "SAME" if same else "DIFF"))
            if not same:
                rc = 1
    print("[frozen] RESULT:", "OK" if rc == 0 else "FAIL")
    return rc


if __name__ == "__main__":
    sys.exit(main())
