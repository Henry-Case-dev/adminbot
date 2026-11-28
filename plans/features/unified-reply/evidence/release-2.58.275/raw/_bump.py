"""Version-only bump 2.58.274 -> 2.58.275 on the release worktree (byte level).

Canonical file set = the 29 product/test/tool files of the previous release
bump commit (5e38d9b72, 2.58.272 -> 2.58.273), excluding that commit's own
evidence artifacts. Files whose whole-file version literals were replaced by
`tests/version_contract.py` (release/test barriers corrective, included in this
release) no longer carry the literal and are reported as skipped-by-contract,
not silently dropped.
"""
import subprocess
from pathlib import Path

ROOT = Path(subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
    check=True, cwd=Path(__file__).parent).stdout.strip())
OUT = Path(__file__).with_name("bump-verify.txt")
BASE = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                      capture_output=True, text=True, check=True).stdout.strip()
OLD = b"2.58.274"
NEW = b"2.58.275"
FILELIST_COMMIT = "5e38d9b72"  # canonical bump set from 2.58.272 -> 2.58.273

files = subprocess.run(
    ["git", "show", "--name-only", "--format=", FILELIST_COMMIT],
    cwd=ROOT, capture_output=True, text=True, check=True,
).stdout.split()
files = [f for f in files if "/evidence/" not in f and (ROOT / f).exists()]

lines = []
total_old = 0
changed = 0
skipped = []
crlf_total = 0
bare_lf_total = 0
sizes = []
for rel in files:
    p = ROOT / rel
    before = p.read_bytes()
    n = before.count(OLD)
    crlf = before.count(b"\r\n")
    bare_lf = before.count(b"\n") - crlf
    crlf_total += crlf
    bare_lf_total += bare_lf
    if n == 0:
        skipped.append(rel)
        continue
    after = before.replace(OLD, NEW)
    p.write_bytes(after)
    total_old += n
    changed += 1
    if len(before) != len(after):
        sizes.append(rel)
    lines.append(f"{rel}: occurrences={n} crlf={crlf} bare_lf={bare_lf} "
                 f"size_before={len(before)} size_after={len(after)}")

settings_text = (ROOT / "config/settings.py").read_text(encoding="utf-8")
app_lines = [ln[:90] for ln in settings_text.splitlines() if ln.startswith("APP_VERSION")]

remaining = sum((ROOT / f).read_bytes().count(OLD) for f in files)
new_present = sum((ROOT / f).read_bytes().count(NEW) for f in files)

# any leftover literal anywhere in the tracked product/test/tool set
leftovers = subprocess.run(
    ["git", "grep", "-n", "2.58.274", "--", "config", "tests", "tools", "services", "web", "plans/docs"],
    cwd=ROOT, capture_output=True, text=True).stdout.strip().splitlines()

diff = subprocess.run(
    ["git", "diff", "-U0", BASE, "--", *files],
    cwd=ROOT, capture_output=True, text=True, check=True,
).stdout
removed = [ln[1:] for ln in diff.splitlines()
           if ln.startswith("-") and not ln.startswith("---")]
added = [ln[1:] for ln in diff.splitlines()
         if ln.startswith("+") and not ln.startswith("+++")]
mapped = all(r.replace("2.58.274", "2.58.275") in set(added) for r in removed)
non_version_pairs = sum(
    1 for r in removed if r.replace("2.58.274", "2.58.275") not in set(added))
non_version_added = sum(
    1 for a in added if a.replace("2.58.275", "2.58.274") not in set(removed))

hdr = [
    f"base_commit={BASE}",
    f"files_in_canonical_set={len(files)} files_changed={changed} "
    f"occurrences_replaced={total_old}",
    f"skipped_no_occurrence={skipped or '(none)'}",
    f"removed_lines={len(removed)} added_lines={len(added)}",
    f"all_removed_map_to_added_by_version={mapped}",
    f"non_version_changed_pairs={non_version_pairs} non_version_added_lines={non_version_added}",
    f"remaining_old_occurrences={remaining} new_occurrences={new_present}",
    f"size_changed_files={sizes or '(none)'}",
    f"crlf_total={crlf_total} bare_lf_total={bare_lf_total}",
    f"APP_VERSION_lines={app_lines}",
    f"leftover_2_58_274_lines={(leftovers or '(none)')}",
    "",
] + lines

OUT.write_text("\n".join(hdr) + "\n", encoding="utf-8")
print("\n".join(hdr))
