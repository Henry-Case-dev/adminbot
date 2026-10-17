"""FS-HOTFIX: проверка «полигон/стекло не тронуты» + границы диффа.

Инварианты владельца (18.10): точечный хотфикс — не менять полигон/палитру/
карточки/Liquid Glass, не затрагивать SOUL-1/Summary и другие незавершённые
функции. Проверяется по факту диффа рабочего дерева против HEAD:

  1) ни одна добавленная/удалённая строка в web/** , tools/ui_*fullscreen*,
     tools/ui_soul1_* и tests/js/asap8_w2_fullscreen_policy_test.js не
     касается полигона/линзы/--lg-*/aurora;
  2) в web/static/ изменены РОВНО два файла: app.css и fullscreen-policy.js;
  3) base64-блоб полигона в web/index.html и блоки #lg-lens / --lg-* в
     app.css совпадают с HEAD; ассеты glass/polygon не изменены;
  4) тронутые файлы — LF-only (CRLF=0).

Запуск: .venv/Scripts/python.exe plans/features/soul-1/evidence/fs-hotfix/frozen_check.py
"""
import hashlib
import io
import os
import re
import subprocess
import sys

def _find_repo():
    d = os.path.dirname(os.path.abspath(__file__))
    while True:
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            raise RuntimeError("repo root not found")
        d = nd


REPO = _find_repo()
LANE_FILES = [
    "web/index.html", "web/app.js", "web/static/app.css",
    "web/static/fullscreen-policy.js",
    "tools/ui_asap8_w2_fullscreen_e2e.py",
    "tools/ui_asap8_w2_shell_e2e.py",
    "tools/ui_soul1_w7_fullscreen_explain_e2e.py",
    "tests/js/asap8_w2_fullscreen_policy_test.js",
    "tests/js/asap8_w2_shell_mobile_nav_test.js",
    "tests/test_webapp_avatars_ui.py",
]
PATTERNS = [r"lg-lens", r"--lg-", r"polygon", r"#aurora", r"lgGlass",
            r"scale=.32.", r"lg-lens-map", r"liquidglass"]
FROZEN_BLOB_RE = r"data:image/[a-z]+;base64,([A-Za-z0-9+/=]{2000,})"
FROZEN_ASSETS = [
    "web/static/vendor/lg-lens-map.png",
    "web/static/vendor/liquidglass.core.0.5.3.min.js",
]


def run(*args):
    p = subprocess.run(list(args), cwd=REPO, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    return p.stdout


def sha8(text):
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:8]


def main():
    rc = 0
    diff = run("git", "diff", "-U0", "--", *LANE_FILES)
    hits = []
    for line in diff.splitlines():
        if line.startswith(("+", "-")) and not line.startswith(("+++", "---")):
            for pat in PATTERNS:
                if re.search(pat, line):
                    hits.append((pat, line[:160]))
    print("[frozen] подозрительные строки диффа (полигон/стекло):", len(hits))
    for pat, line in hits:
        print("   ", pat, "|", line)
    if hits:
        rc = 1

    stat = run("git", "diff", "--numstat", "--", "web/static/").strip()
    files = sorted(l.split("\t")[-1] for l in stat.splitlines() if l.strip())
    print("[frozen] изменённые файлы web/static/:", files)
    if files != ["web/static/app.css", "web/static/fullscreen-policy.js"]:
        print("[frozen] ОЖИДАЛОСЬ ровно app.css + fullscreen-policy.js")
        rc = 1

    for rel in FROZEN_ASSETS:
        head = run("git", "rev-parse", "HEAD:" + rel).strip()
        work = run("git", "rev-parse", ":" + rel).strip()
        same = head == work and bool(head)
        print("[frozen] ассет %s HEAD=%s WORK=%s -> %s"
              % (rel, head[:12], work[:12], "SAME" if same else "DIFF"))
        if not same:
            rc = 1

    for rel in ("web/index.html", "web/static/app.css"):
        head = run("git", "show", "HEAD:" + rel)
        work = io.open(os.path.join(REPO, rel.replace("/", os.sep)),
                       encoding="utf-8", newline="").read().replace("\r\n", "\n")
        head_n = head.replace("\r\n", "\n")
        if rel.endswith("index.html"):
            hb = [sha8(m) for m in re.findall(FROZEN_BLOB_RE, head_n)]
            wb = [sha8(m) for m in re.findall(FROZEN_BLOB_RE, work)]
            ok = hb == wb and bool(hb)
            print("[frozen] %s polygon-blobs HEAD=%s WORK=%s -> %s"
                  % (rel, hb, wb, "SAME" if ok else "DIFF"))
            if not ok:
                rc = 1
        for name, anchor, span in (("lens", "#lg-lens", 1500),
                                   ("tokens", "--lg-", 3000)):
            i, j = head_n.find(anchor), work.find(anchor)
            if i < 0 and j < 0:
                print("[frozen] %s %s: токена нет ни в HEAD, ни в worktree" %
                      (rel, name))
                continue
            same = (i >= 0 and j >= 0
                    and sha8(head_n[i:i + span]) == sha8(work[j:j + span]))
            print("[frozen] %s %s block HEAD=%s WORK=%s -> %s"
                  % (rel, name, sha8(head_n[i:i + span]) if i >= 0 else "n/a",
                     sha8(work[j:j + span]) if j >= 0 else "n/a",
                     "SAME" if same else "DIFF"))
            if not same:
                rc = 1

    for rel in LANE_FILES:
        p = os.path.join(REPO, rel.replace("/", os.sep))
        if not os.path.exists(p):
            continue
        raw = io.open(p, "rb").read()
        head_raw = subprocess.run(["git", "show", "HEAD:" + rel], cwd=REPO,
                                  capture_output=True).stdout
        crlf = raw.count(b"\r\n")
        crlf_head = head_raw.count(b"\r\n")
        verdict = "OK" if crlf <= crlf_head else "NEW-CRLF"
        print("[frozen] %s CRLF=%d (HEAD=%d) -> %s" % (rel, crlf, crlf_head, verdict))
        if crlf > crlf_head:
            rc = 1
    print("[frozen] RESULT:", "OK" if rc == 0 else "FAIL")
    return rc


if __name__ == "__main__":
    sys.exit(main())
