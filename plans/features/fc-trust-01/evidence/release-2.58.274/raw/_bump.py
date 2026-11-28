"""Version-only bump 2.58.273 -> 2.58.274 on the release worktree (byte level).

Canonical file set = the 29 product/test/tool files touched by the previous
release bump commit 5e38d9b72 (2.58.272 -> 2.58.273), excluding that commit's
own evidence raw artifacts, which are historical evidence and keep their own
version literals. CRLF/LF are preserved because the replacement is a byte
substitution inside otherwise unchanged lines.
"""
import subprocess
from pathlib import Path

ROOT = Path(subprocess.run(
    ["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True,
    check=True, cwd=Path(__file__).parent).stdout.strip())
OUT = Path(__file__).with_name("bump-verify.txt")
BASE = subprocess.run(["git", "rev-parse", "HEAD"], cwd=ROOT,
                      capture_output=True, text=True, check=True).stdout.strip()
OLD = b"2.58.273"
NEW = b"2.58.274"
FILELIST_COMMIT = "5e38d9b72"  # 2.58.272 -> 2.58.273 bump: canonical bump set

files = subprocess.run(
    ["git", "show", "--name-only", "--format=", FILELIST_COMMIT],
    cwd=ROOT, capture_output=True, text=True, check=True,
).stdout.split()
files = [f for f in files if "/evidence/" not in f]

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

diff = subprocess.run(
    ["git", "diff", "-U0", BASE, "--", *files],
    cwd=ROOT, capture_output=True, text=True, check=True,
).stdout
removed = [ln[1:] for ln in diff.splitlines()
           if ln.startswith("-") and not ln.startswith("---")]
added = [ln[1:] for ln in diff.splitlines()
         if ln.startswith("+") and not ln.startswith("+++")]
mapped = all(r.replace("2.58.273", "2.58.274") in set(added) for r in removed)
non_version_pairs = sum(
    1 for r in removed if r.replace("2.58.273", "2.58.274") not in set(added))
non_version_added = sum(
    1 for a in added if a.replace("2.58.274", "2.58.273") not in set(removed))

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
    "",
] + lines

OUT.write_text("\n".join(hdr) + "\n", encoding="utf-8")
print("\n".join(hdr))
