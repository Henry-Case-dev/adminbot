"""Version-only bump 2.58.268 -> 2.58.269 on the release worktree (byte level)."""
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
OUT = Path(__file__).with_name("bump-verify.txt")
BASE = "e46aa0696"
OLD = b"2.58.268"
NEW = b"2.58.269"
FILELIST_COMMIT = "9c45a454c"  # 2.58.267 -> 2.58.268 bump commit: canonical 29-file bump set

files = subprocess.run(
    ["git", "show", "--name-only", "--format=", FILELIST_COMMIT],
    cwd=ROOT, capture_output=True, text=True, check=True,
).stdout.split()

lines = []
total_old = 0
changed = 0
skipped = []
for rel in files:
    p = ROOT / rel
    before = p.read_bytes()
    n = before.count(OLD)
    if n == 0:
        skipped.append(rel)
        continue
    after = before.replace(OLD, NEW)
    total_old += n
    p.write_bytes(after)
    changed += 1
    crlf = after.count(b"\r\n")
    bare_lf = after.count(b"\n") - crlf
    lines.append(f"{rel}: occurrences={n} crlf={crlf} bare_lf={bare_lf} "
                 f"size_before={len(before)} size_after={len(after)}")

settings_text = (ROOT / "config/settings.py").read_text(encoding="utf-8")
app_lines = [ln[:80] for ln in settings_text.splitlines() if ln.startswith("APP_VERSION")]

remaining = sum((ROOT / f).read_bytes().count(OLD) for f in files)

# diff-level proof: every removed line maps to an added line differing only by version
diff = subprocess.run(
    ["git", "diff", "-U0", BASE, "--", *files],
    cwd=ROOT, capture_output=True, text=True, check=True,
).stdout
removed = [ln[1:] for ln in diff.splitlines()
           if ln.startswith("-") and not ln.startswith("---")]
added = [ln[1:] for ln in diff.splitlines()
         if ln.startswith("+") and not ln.startswith("+++")]
mapped = all(r.replace("2.58.268", "2.58.269") in set(added) for r in removed)
non_version_pairs = sum(
    1 for r in removed if r.replace("2.58.268", "2.58.269") not in set(added))

hdr = [
    f"files={changed} occurrences_replaced={total_old}",
    f"skipped_no_occurrence={skipped or '(none)'}",
    f"removed_lines={len(removed)} added_lines={len(added)}",
    f"all_removed_map_to_added_by_version={mapped}",
    f"non_version_changed_pairs={non_version_pairs}",
    f"remaining_old_occurrences={remaining}",
    f"APP_VERSION_lines={app_lines}",
    "",
] + lines

OUT.write_text("\n".join(hdr) + "\n", encoding="utf-8")
print("\n".join(hdr))
