# -*- coding: utf-8 -*-
"""Prove that the OFF-path baseline delta W1 -> ASAP 2 is EXACTLY the planned
L1/L2 canon change (§4.1/§4.2 of plans/features/asap2-direct-chat/
source-2026-10-22.md) and nothing else.

Reads:
  before/direct-runtime-assembly-w1.txt        (committed W1 baseline)
  ../../../../tests/fixtures/soul1/direct-runtime-assembly-asap2.txt (new)
  after/raw-sections.json                      (fresh capture, full bytes)

Writes diff.md. Exit code 1 if any delta is not attributable to the canon.
"""
import difflib
import hashlib
import io
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.abspath(os.path.join(HERE, "..", "..", "..", ".."))
sys.path.insert(0, ROOT)

BEFORE = os.path.join(HERE, "before", "direct-runtime-assembly-w1.txt")
AFTER = os.path.join(ROOT, "tests", "fixtures", "soul1",
                     "direct-runtime-assembly-asap2.txt")
RAW = os.path.join(HERE, "after", "raw-sections.json")
OUT = os.path.join(HERE, "diff.md")

ORDER = ["P1", "P2", "P3", "P5a", "P5b", "P4"]

_METRICS = re.compile(
    r"^(SYSTEM|USER)\s+chars=(\d+)\s+tokens=(-?\d+)\s+sha256_12=([0-9a-f]{12})$",
    re.MULTILINE)


def sha12(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:12]


def parse_dump(path):
    text = io.open(path, encoding="utf-8").read()
    parts = re.split(r"(?m)^## (\w+)", text)
    out = {}
    for i in range(1, len(parts), 2):
        name, body = parts[i], parts[i + 1]
        metrics = {}
        for kind, chars, tokens, sha in _METRICS.findall(body):
            metrics[kind] = (int(chars), int(tokens), sha)
        rest = body[body.index("[SYSTEM]\n") + len("[SYSTEM]\n"):]
        if "\n\n[USER]\n" in rest:
            system, user = rest.split("\n\n[USER]\n", 1)
            user = user.rstrip("\n")
        else:
            system, user = rest.rstrip("\n"), None
        out[name] = {"system": system, "user": user, "metrics": metrics}
    return out


def lines_of(text):
    return text.split("\n") if text is not None else []


def main():
    from services.chat_prompts import (            # noqa: E402
        DIRECT_L1_PLANNER_SYSTEM_PROMPT,
        DIRECT_VERBALIZER_SYSTEM_PROMPT,
        PREV_CHAT_VERBALIZER_W1_31,
        PREV_DIRECT_L1_PLANNER_W1,
        _DIRECT_L1_CLARIFICATION_CONTRACT as CONTRACT,
        _DIRECT_L1_PLANNER_BASE as BASE,
        _DIRECT_L1_PLANNER_RULES as RULES,
        _DIRECT_L1_PLANNER_RULES_W1 as RULES_W1,
        _VERBALIZER_CLAR_PARAGRAPHS as PARAGRAPHS,
        _VERBALIZER_KAK_PISAT_ANCHOR as ANCHOR,
    )

    before = parse_dump(BEFORE)
    after = parse_dump(AFTER)
    raw = json.load(io.open(RAW, encoding="utf-8"))
    assert set(before) == set(ORDER), sorted(before)
    assert set(after) == set(ORDER), sorted(after)

    checks = []

    def check(name, ok, detail=""):
        checks.append((name, bool(ok), detail))

    # 1. New dump is byte-identical to a fresh capture (no hand edits).
    for name in ORDER:
        for kind in ("system", "user"):
            want = raw[name][kind]
            got = after[name][kind]
            check(f"{name}/{kind}: dump==fresh capture", got == want,
                  f"len {len(got or '')} vs {len(want or '')}")
        # metrics lines agree with the recorded bytes
        sys_chars, _, sys_sha = after[name]["metrics"]["SYSTEM"]
        check(f"{name}: SYSTEM metrics self-consistent",
              sys_chars == len(after[name]["system"])
              and sys_sha == sha12(after[name]["system"]),
              f"{sys_chars}/{sys_sha}")
        if after[name]["user"] is not None:
            u_chars, _, u_sha = after[name]["metrics"]["USER"]
            check(f"{name}: USER metrics self-consistent",
                  u_chars == len(after[name]["user"])
                  and u_sha == sha12(after[name]["user"]),
                  f"{u_chars}/{u_sha}")

    # 2. Sections whose canon was NOT touched must be byte-identical.
    for name in ("P3", "P5a"):
        for kind in ("system", "user"):
            check(f"{name}/{kind}: untouched by ASAP 2",
                  before[name][kind] == after[name][kind],
                  f"sha {sha12(before[name][kind])} -> "
                  f"{sha12(after[name][kind])}")

    # 3. L2 writer sections: canon prefix changed by exactly the §4.2 insert;
    #    every other layer byte-identical.
    for name in ("P1", "P2", "P5b"):
        old, new = before[name], after[name]
        old_sys, new_sys = old["system"], new["system"]
        check(f"{name}: old canon part == frozen W1 canon",
              old_sys.startswith(PREV_CHAT_VERBALIZER_W1_31),
              f"PREV sha {sha12(PREV_CHAT_VERBALIZER_W1_31)}")
        check(f"{name}: new canon part == active ASAP 2 canon",
              new_sys.startswith(DIRECT_VERBALIZER_SYSTEM_PROMPT),
              f"CUR sha {sha12(DIRECT_VERBALIZER_SYSTEM_PROMPT)}")
        check(f"{name}: non-canon tail (persona/style) unchanged",
              old_sys[len(PREV_CHAT_VERBALIZER_W1_31):]
              == new_sys[len(DIRECT_VERBALIZER_SYSTEM_PROMPT):],
              repr(old_sys[len(PREV_CHAT_VERBALIZER_W1_31):][:40]))
        # The only textual delta inside the canon is one insertion of §4.2.
        expect = PREV_CHAT_VERBALIZER_W1_31.replace(
            ANCHOR, ANCHOR + "\n\n" + PARAGRAPHS, 1)
        check(f"{name}: active canon == W1 canon + §4.2 insert @КАК ПИСАТЬ",
              expect == DIRECT_VERBALIZER_SYSTEM_PROMPT,
              f"+{len(PARAGRAPHS) + 2} chars")
        old_lines, new_lines = lines_of(old_sys), lines_of(new_sys)
        ops = [o for o in difflib.SequenceMatcher(
            None, old_lines, new_lines).get_opcodes() if o[0] != "equal"]
        check(f"{name}: exactly ONE changed hunk in SYSTEM",
              len(ops) == 1 and ops[0][0] == "insert",
              str([(o[0], o[2] - o[1], o[4] - o[3]) for o in ops]))
        if len(ops) == 1:
            added = "\n".join(new_lines[ops[0][3]:ops[0][4]])
            check(f"{name}: inserted hunk == owner §4.2 paragraphs",
                  added.strip("\n") == PARAGRAPHS,
                  f"{len(added)} chars")
        if old["user"] is not None and new["user"] is not None:
            check(f"{name}/user: payload byte-identical (no loss/reorder)",
                  old["user"] == new["user"],
                  f"{len(old['user'])} chars sha {sha12(old['user'])}")

    # 4. L1 planner: base + §3.7 (W1) stay byte-identical; only the §4.1
    #    contract + rule 5 change.
    old4, new4 = before["P4"]["system"], after["P4"]["system"]
    check("P4: old planner == frozen W1 canon",
          old4 == PREV_DIRECT_L1_PLANNER_W1,
          f"sha {sha12(old4)}")
    check("P4: old planner == BASE + RULES_W1",
          old4 == BASE + RULES_W1, "")
    check("P4: new planner == active ASAP 2 canon",
          new4 == DIRECT_L1_PLANNER_SYSTEM_PROMPT, f"sha {sha12(new4)}")
    check("P4: new planner == BASE + CONTRACT + RULES",
          new4 == BASE + CONTRACT + RULES, "")
    check("P4: BASE (schema/ВЫБОР УЧАСТИЯ §3.7) byte-identical",
          new4.startswith(BASE) and old4.startswith(BASE),
          f"BASE {len(BASE)} chars")
    # Rule 5: old semantic rule gone, new reference in place.
    old_rule5 = [ln for ln in RULES_W1.split("\n")
                 if ln.startswith("5. needs_clarification")]
    new_rule5 = [ln for ln in RULES.split("\n")
                 if ln.startswith("5. needs_clarification")]
    check("P4: rule 5 replaced (old semantic rule removed)",
          bool(old_rule5) and old_rule5[0] not in new4, old_rule5[0][:60])
    check("P4: rule 5 now references the contract section",
          bool(new_rule5) and new_rule5[0] in new4
          and "УТОЧНЕНИЯ" in new_rule5[0], new_rule5[0][:60])
    # Every non-equal hunk must be a slice of the two documented fragments.
    old_l, new_l = lines_of(old4), lines_of(new4)
    allowed_old = set(RULES_W1.split("\n"))
    allowed_new = set(CONTRACT.split("\n")) | set(RULES.split("\n"))
    unexplained = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(
            None, old_l, new_l).get_opcodes():
        if tag == "equal":
            continue
        for ln in old_l[i1:i2]:
            if ln not in allowed_old:
                unexplained.append(("removed", ln))
        for ln in new_l[j1:j2]:
            if ln not in allowed_new:
                unexplained.append(("added", ln))
    check("P4: no hunk outside §4.1 contract / rule 5", not unexplained,
          str(unexplained[:3]))

    failed = [c for c in checks if not c[1]]

    # ── report ────────────────────────────────────────────────────────────
    rows = []
    for name in ORDER:
        for kind in ("system", "user"):
            o, n = before[name][kind], after[name][kind]
            if o is None and n is None:
                continue
            if o is None or n is None:
                rows.append(f"| {name} | {kind} | — | "
                            f"{len(n or '')} / `{sha12(n)}` | not recorded "
                            f"before |")
                continue
            mark = "same" if o == n else f"+{len(n) - len(o)} chars"
            rows.append(f"| {name} | {kind} | {len(o)} / `{sha12(o)}` | "
                        f"{len(n)} / `{sha12(n)}` | {mark} |")

    diffs = []
    for name in ORDER:
        for kind in ("system", "user"):
            o, n = before[name][kind], after[name][kind]
            if o == n or o is None or n is None:
                continue
            d = list(difflib.unified_diff(
                lines_of(o), lines_of(n),
                fromfile=f"{name}/{kind} @ W1 (0f3ed53a)",
                tofile=f"{name}/{kind} @ ASAP 2 (5ad73933)",
                lineterm="", n=2))
            diffs.append(f"### {name} — {kind}\n\n```diff\n"
                         + "\n".join(d) + "\n```\n")

    with io.open(OUT, "w", encoding="utf-8", newline="\n") as fh:
        fh.write("# OFF-path baseline delta: W1 canons -> ASAP 2 canons\n\n")
        fh.write("Generated by `diff_analysis.py` (same directory). "
                 "Every delta below is checked against the code constants, "
                 "not eyeballed.\n\n")
        fh.write("## Metrics before/after\n\n"
                 "| Section | Part | W1 baseline | ASAP 2 baseline | Delta |\n"
                 "|---|---|---|---|---|\n" + "\n".join(rows) + "\n\n")
        fh.write("## Checks\n\n| # | Check | Result | Detail |\n"
                 "|---|---|---|---|\n")
        for idx, (nm, ok, det) in enumerate(checks, 1):
            fh.write(f"| {idx} | {nm} | {'PASS' if ok else 'FAIL'} | "
                     f"{det.replace('|', '/')} |\n")
        fh.write(f"\nTotal: {len(checks) - len(failed)} PASS, "
                 f"{len(failed)} FAIL.\n\n")
        fh.write("## Diffs\n\n" + "\n".join(diffs))

    print(f"checks: {len(checks) - len(failed)} PASS / {len(failed)} FAIL")
    for nm, ok, det in failed:
        print("FAIL:", nm, "|", det)
    print("written", OUT)
    return 1 if failed else 0


sys.exit(main())
