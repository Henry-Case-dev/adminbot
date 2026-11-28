# -*- coding: utf-8 -*-
"""Release 2.58.265 version-only bump (2.58.264 -> 2.58.265).

Byte-safe: replaces the exact ASCII bytes b"2.58.264" with b"2.58.265" in every
tracked file that contains it, excluding historical evidence under plans/.
Verifies that every changed line pair differs only by the version string.
"""
import io
import os
import subprocess
import sys

ROOT = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, check=True).stdout.decode().strip()
OLD = "2.58.264"
NEW = "2.58.265"


def git(*args):
    return subprocess.run(["git", *args], cwd=ROOT, capture_output=True, check=True).stdout


tracked = git("ls-files").decode("utf-8").splitlines()
targets = []
for rel in tracked:
    if rel.startswith("plans/features/"):
        continue
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    try:
        with io.open(p, "rb") as f:
            raw = f.read()
    except OSError:
        continue
    if OLD.encode() in raw:
        targets.append((rel, raw.count(OLD.encode())))

print("files=%d occurrences=%d" % (len(targets), sum(n for _, n in targets)))
for rel, n in targets:
    print("  %d\t%s" % (n, rel))

if len(targets) != 29 or sum(n for _, n in targets) != 34:
    print("UNEXPECTED TARGET SET", file=sys.stderr)
    sys.exit(2)

for rel, n in targets:
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    with io.open(p, "rb") as f:
        raw = f.read()
    new = raw.replace(OLD.encode(), NEW.encode())
    with io.open(p, "wb") as f:
        f.write(new)

# verify
diff = git("diff", "-U0").decode("utf-8", "replace").splitlines()
files = set()
removed = []
added = []
for line in diff:
    if line.startswith("+++ b/"):
        files.add(line[6:])
    elif line.startswith("--- a/"):
        pass
    elif line.startswith("-") and not line.startswith("---"):
        removed.append(line[1:])
    elif line.startswith("+") and not line.startswith("+++"):
        added.append(line[1:])

mapped_ok = True
for r, a in zip(removed, added):
    if r.replace(OLD, NEW) != a:
        mapped_ok = False
        print("PAIR-MISMATCH:\n  -%s\n  +%s" % (r, a))

non_version = sum(1 for r, a in zip(removed, added) if r.replace(OLD, NEW) != a)
print("files=%d additions=%d deletions=%d" % (len(files), len(added), len(removed)))
print("removed_lines=%d added_lines=%d" % (len(removed), len(added)))
print("all_removed_map_to_added_by_version=%s" % mapped_ok)
print("non_version_changed_pairs=%d" % non_version)
print("pairs_differing_only_by_version=%d/%d" % (len(added) - non_version, len(added)))
print("version_only_bump=%s" % ("OK" if mapped_ok and non_version == 0 and len(added) == 34 else "FAIL"))

settings = os.path.join(ROOT, "config", "settings.py")
with io.open(settings, "rb") as f:
    sraw = f.read()
crlf = sraw.count(b"\r\n")
bare_lf = sraw.count(b"\n") - crlf
print("eol_settings: crlf=%d bare_lf=%d size=%d" % (crlf, bare_lf, len(sraw)))
app = [l.decode() for l in sraw.splitlines() if l.startswith(b"APP_VERSION")]
print("APP_VERSION=%s" % (app[0].split('"')[1] if app else "MISSING"))
