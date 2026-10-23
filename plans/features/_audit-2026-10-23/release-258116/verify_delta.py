# -*- coding: utf-8 -*-
"""Prove the SOUL-1 OFF-baseline delta is exactly R3 §3.7 + R3B canon text.

Inputs (all artifacts are byte-exact files in this folder):
  parity-before.txt              old baseline, recorded on ASAP 2 canons (5ad73933)
  parity-base-regen.txt          same stand replayed on the ASAP 2 code state
  parity-after.txt               new baseline, recorded on the 2.58.115 line

Checks
  1. base replay == old baseline, section by section (the old artifact is the
     stand's output on ASAP 2 code, not a hand-edited file).
  2. every section transforms by EXACT string surgery with the canon constants:
       P1/P2/P5b : + "\\n\\n" + _VERBALIZER_HISTORY_BOUNDARY_R3B      (R3B)
       P4        : _DIRECT_L1_PARTICIPATION_W1 -> _..._R3             (R3 §3.7)
                   + _DIRECT_L1_CONTINUATION_R3B                      (R3B)
     Equality after the surgery proves no other byte changed.
  3. P3 (legacy modes-OFF base) and P5a (synthesizer) are byte-identical —
     R3/R3B did not touch them.
  4. the constants were introduced by af7de4e9 (R3) / a8d047a7 (R3B) and were
     absent from their parents.

Writes diff.md next to itself; exits non-zero on any failed check.
"""
import difflib
import hashlib
import io
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, ROOT)

from services import chat_prompts as cp                      # noqa: E402

BEFORE = os.path.join(HERE, "parity-before.txt")
BASE = os.path.join(HERE, "parity-base-regen.txt")
AFTER = os.path.join(HERE, "parity-after.txt")

_SYS_RE = re.compile(r"^SYSTEM\s+chars=(\d+)\s+tokens=(-?\d+)\s+"
                     r"sha256_12=([0-9a-f]{12})", re.MULTILINE)
_USER_RE = re.compile(r"^USER\s+chars=(\d+)\s+tokens=(-?\d+)\s+"
                      r"sha256_12=([0-9a-f]{12})", re.MULTILINE)
SECTIONS = ("P1", "P2", "P3", "P5a", "P5b", "P4")


def sha12(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def blocks(tail):
    start = tail.index("[SYSTEM]\n") + len("[SYSTEM]\n")
    rest = tail[start:]
    marker = "\n\n[USER]\n"
    if marker in rest:
        system, user = rest.split(marker, 1)
        return system, user.rstrip("\n")
    return rest.rstrip("\n"), None


def parse(path):
    text = io.open(path, encoding="utf-8").read()
    out = {}
    for name in SECTIONS:
        start = text.index(f"## {name}")
        tail = text[start:]
        nxt = tail.find("\n## ", 1)
        if nxt != -1:
            tail = tail[:nxt]
        sys_m = _SYS_RE.search(tail)
        user_m = _USER_RE.search(tail)
        system, user = blocks(tail)
        assert sys_m and sha12(system) == sys_m.group(3)
        assert len(system) == int(sys_m.group(1))
        if user_m:
            assert user is not None and sha12(user) == user_m.group(3)
            assert len(user) == int(user_m.group(1))
        out[name] = {"system": system, "user": user,
                     "chars": int(sys_m.group(1)),
                     "token": int(sys_m.group(2)),
                     "sha": sys_m.group(3),
                     "uchars": int(user_m.group(1)) if user_m else None,
                     "utoken": int(user_m.group(2)) if user_m else None,
                     "usha": user_m.group(3) if user_m else None}
    return out


def section_diff(name, old, new):
    d = difflib.unified_diff(
        old.splitlines(keepends=True), new.splitlines(keepends=True),
        fromfile=f"{name}/before", tofile=f"{name}/after", n=1)
    return "".join(d)


def git(args):
    return subprocess.run(["git"] + args, cwd=ROOT, capture_output=True,
                          check=True).stdout.decode("utf-8", "replace")


def main():
    before, base, after = parse(BEFORE), parse(BASE), parse(AFTER)
    errors = []
    report = []

    def check(label, cond, detail=""):
        report.append(f"- {'OK ' if cond else 'FAIL'} {label}"
                      + (f" | {detail}" if detail else ""))
        if not cond:
            errors.append(label + " | " + detail)

    for name in SECTIONS:
        check(f"{name}: base replay == old baseline",
              base[name]["system"] == before[name]["system"]
              and base[name]["user"] == before[name]["user"],
              f"base {base[name]['chars']}/{base[name]['sha']} vs "
              f"before {before[name]['chars']}/{before[name]['sha']}")

    boundary = ("\n\n" + cp._VERBALIZER_HISTORY_BOUNDARY_R3B)
    expected = {}
    detail = {}
    for name in ("P1", "P2", "P5b"):
        old = before[name]["system"]
        check(f"{name}: clar paragraphs present exactly once",
              old.count(cp._VERBALIZER_CLAR_PARAGRAPHS) == 1)
        check(f"{name}: R3B boundary absent before",
              cp._VERBALIZER_HISTORY_BOUNDARY_R3B not in old)
        expected[name] = old.replace(
            cp._VERBALIZER_CLAR_PARAGRAPHS,
            cp._VERBALIZER_CLAR_PARAGRAPHS
            + boundary, 1)
        detail[name] = (
            "insert R3B L2 history-boundary instruction (+"
            f"{len(boundary)} chars) after §3.1 «КАК ПИСАТЬ»")
    for name in ("P3", "P5a"):
        expected[name] = before[name]["system"]
        detail[name] = "unchanged: R3/R3B do not touch this canon"

    old_p4 = before["P4"]["system"]
    check("P4: W1 participation block present exactly once",
          old_p4.count(cp._DIRECT_L1_PARTICIPATION_W1) == 1)
    check("P4: R3 participation block absent before",
          cp._DIRECT_L1_PARTICIPATION_R3 not in old_p4)
    check("P4: R3B continuation absent before",
          cp._DIRECT_L1_CONTINUATION_R3B not in old_p4)
    p4 = old_p4.replace(cp._DIRECT_L1_PARTICIPATION_W1,
                        cp._DIRECT_L1_PARTICIPATION_R3, 1)
    p4 = p4.replace(cp._DIRECT_L1_CLARIFICATION_CONTRACT,
                    cp._DIRECT_L1_CLARIFICATION_CONTRACT
                    + cp._DIRECT_L1_CONTINUATION_R3B, 1)
    expected["P4"] = p4
    detail["P4"] = (
        "§3.7 participation W1->R3 (%d -> %d chars) + R3B continuation "
        "(+%d chars after §4.1 contract)"
        % (len(cp._DIRECT_L1_PARTICIPATION_W1),
           len(cp._DIRECT_L1_PARTICIPATION_R3),
           len(cp._DIRECT_L1_CONTINUATION_R3B)))

    for name in SECTIONS:
        check(f"{name}: after == before + only R3/R3B canon surgery",
              after[name]["system"] == expected[name],
              f"after {after[name]['chars']}/{after[name]['sha']} vs "
              f"expected {len(expected[name])}/{sha12(expected[name])}")
        check(f"{name}: USER part unchanged",
              after[name]["user"] == before[name]["user"],
              "" if after[name]["user"] == before[name]["user"]
              else "user payload differs")

    # Provenance of the constants: introduced by the R3 / R3B commits.
    probes = [
        ("R3 §3.7 block", cp._DIRECT_L1_PARTICIPATION_R3, "af7de4e9",
         "Сначала определи содержание своей мысли"),
        ("R3B continuation", cp._DIRECT_L1_CONTINUATION_R3B, "a8d047a7",
         "считай недостающий предмет названным"),
        ("R3B L2 boundary", cp._VERBALIZER_HISTORY_BOUNDARY_R3B, "a8d047a7",
         "один раз естественно назови это ограничение"),
    ]
    for label, text, commit, needle in probes:
        assert needle in text, (label, needle)
        assert needle.count("\n") == 0
        hits = git(["log", "--oneline", "-S", needle, "--",
                    "services/chat_prompts.py"]).strip().splitlines()
        first = hits[-1].split()[0] if hits else "<none>"
        have = git(["show", f"{commit}:services/chat_prompts.py"]).find(
            needle) != -1
        parent = git(["show", f"{commit}^:services/chat_prompts.py"]).find(
            needle) == -1
        check(f"{label}: introduced by {commit}", have and parent,
              f"blame-first={first}")

    rows = []
    md = ["# SOUL-1 OFF parity: delta proof (2.58.116)", "",
          "Reference artifact re-recorded with the SAME stand as the test:",
          "`tests/test_soul1_composer_parity_off.py` (offline, PG down, no",
          "Telegram/LLM/DB). Old baseline came from ASAP 2 canons (5ad73933,",
          "FACTORY_SET `24ae494ac422`); active line is 2.58.114+ (R3 §3.7",
          "`af7de4e9` + R3B `a8d047a7`, FACTORY_SET `0163a686c401`).", "",
          "## Arithmetic", "",
          "| section | old chars | new chars | Δ | old sha | new sha | change |",
          "|---|---|---|---|---|---|---|"]
    total_old = total_new = 0
    for name in SECTIONS:
        total_old += before[name]["chars"]
        total_new += after[name]["chars"]
        md.append("| %s | %d | %d | %+d | `%s` | `%s` | %s |" % (
            name, before[name]["chars"], after[name]["chars"],
            after[name]["chars"] - before[name]["chars"],
            before[name]["sha"], after[name]["sha"], detail[name]))
        rows.append("%s: before %d/%s -> after %d/%s (delta %+d)" % (
            name, before[name]["chars"], before[name]["sha"],
            after[name]["chars"], after[name]["sha"],
            after[name]["chars"] - before[name]["chars"]))
    md += ["", "Total SYSTEM chars: %d -> %d (%+d). USER payloads: %s." % (
        total_old, total_new, total_new - total_old,
        "byte-identical in all sections"
        if all(after[n]["user"] == before[n]["user"] for n in SECTIONS)
        else "CHANGED (see below)"), "",
        "Canon constants doing the surgery (bytes from `services/chat_prompts.py`):",
        "",
        "- `_DIRECT_L1_PARTICIPATION_W1` = %d chars `%s`" % (
            len(cp._DIRECT_L1_PARTICIPATION_W1),
            sha12(cp._DIRECT_L1_PARTICIPATION_W1)),
        "- `_DIRECT_L1_PARTICIPATION_R3` = %d chars `%s`" % (
            len(cp._DIRECT_L1_PARTICIPATION_R3),
            sha12(cp._DIRECT_L1_PARTICIPATION_R3)),
        "- `_DIRECT_L1_CONTINUATION_R3B` = %d chars `%s`" % (
            len(cp._DIRECT_L1_CONTINUATION_R3B),
            sha12(cp._DIRECT_L1_CONTINUATION_R3B)),
        "- `_VERBALIZER_HISTORY_BOUNDARY_R3B` = %d chars `%s`" % (
            len(cp._VERBALIZER_HISTORY_BOUNDARY_R3B),
            sha12(cp._VERBALIZER_HISTORY_BOUNDARY_R3B)),
        "- `_VERBALIZER_CLAR_PARAGRAPHS` = %d chars `%s`" % (
            len(cp._VERBALIZER_CLAR_PARAGRAPHS),
            sha12(cp._VERBALIZER_CLAR_PARAGRAPHS)),
        "", "## Checks", ""] + report + ["", "## Unified diffs", ""]
    for name in SECTIONS:
        d = section_diff(name, before[name]["system"], after[name]["system"])
        md += [f"### {name}", "", "```diff", d.rstrip("\n") or "(no change)",
               "```", ""]

    io.open(os.path.join(HERE, "diff.md"), "w", encoding="utf-8",
            newline="\n").write("\n".join(md) + "\n")
    print("\n".join(rows))
    print("checks:", len(report) - len(errors), "/", len(report), "OK")
    for line in report:
        print(line)
    if errors:
        print("FAILED:", len(errors))
        return 1
    print("ALL CHECKS PASS")
    return 0


sys.exit(main())
