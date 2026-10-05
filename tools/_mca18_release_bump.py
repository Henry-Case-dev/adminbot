# -*- coding: utf-8 -*-
"""MCA-18 deploy T-5094: release bump 2.58.61 -> 2.58.62 per repo convention.
Touches: APP_VERSION (config/settings.py), README.md version header,
F8 meta pin (plans/docs/param-registry-round1025.meta.md), 20 py release-pin
test files (19 carried from mca-10b list + 3 stale 2.58.57 pins closed:
design_tokens/f6/hotfix6), 4 JS hotfix harness pin regexes (round1025_hotfix
{7,8,9,10} - pinned 2.58.61 since mca-10b; closed by the 2.58.62 release sweep).
Historical mentions in docstrings/comments unchanged.
Precedent: tools/_mca10b_release_bump.py (mca-10b feat 780f77c), mca-09.
"""
import io, os

ROOT = r"C:\Code\Python\adminbot"
changed = []

def patch(rel, pairs, description):
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    with io.open(p, "r", encoding="utf-8", newline="") as f:
        raw = f.read()
    new = raw
    for old, new_v in pairs:
        new = new.replace(old, new_v)
    if new == raw:
        print("NO-CHANGE", rel, description)
        return
    with io.open(p, "w", encoding="utf-8", newline="") as f:
        f.write(new)
    changed.append(rel)
    print("PATCHED", rel, description)

# 1. APP_VERSION
patch("config/settings.py", [('APP_VERSION = "2.58.61"', 'APP_VERSION = "2.58.62"')], "APP_VERSION")

# 2. README version header
p = os.path.join(ROOT, "README.md")
raw = io.open(p, "r", encoding="utf-8", newline="").read()
raw2 = raw.replace("**Версия:** v2.58.61", "**Версия:** v2.58.62", 1)
assert raw2 != raw, "README version header not found"
io.open(p, "w", encoding="utf-8", newline="").write(raw2)
changed.append("README.md")
print("PATCHED README.md header")

# 3. F8 meta pin
patch("plans/docs/param-registry-round1025.meta.md",
      [('- **APP_VERSION:** `2.58.61`', '- **APP_VERSION:** `2.58.62`')], "F8 meta-pin")

# 4. py pins 2.58.61 -> 2.58.62 (mca-10b list)
py_pins = [
    "tests/test_decision_making_round1026.py",
    "tests/test_image_context_memory_round1026.py",
    "tests/test_round1025_f8_registry.py",
    "tests/test_scope_selector_round1025.py",
    "tests/test_summary_fact_package.py",
    "tests/test_summary_deploy_round1026.py",
    "tests/test_summary_logging_runid.py",
    "tests/test_summary_publish_integration_round1026.py",
    "tests/test_summary_test_run.py",
    "tests/test_telegram_reactions_round1026.py",
    "tests/test_unified_image_request_round1026.py",
    "tests/test_tool_coordinator_round1026.py",
    "tests/test_webapp_f11_round1025.py",
    "tests/test_webapp_f7_round1025.py",
    "tests/test_webapp_f9_round1025.py",
    "tests/test_webapp_hotfix7_round1025.py",
    "tests/test_webapp_hotfix8_round1025.py",
    "tests/test_webapp_hotfix9_round1025.py",
    "tests/test_webapp_hotfix10_round1025.py",
    "tests/test_webapp_round1026_polygon.py",
]
for rel in py_pins:
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    raw = io.open(p, "r", encoding="utf-8", newline="").read()
    n = raw.count("2.58.61")
    new = raw.replace("2.58.61", "2.58.62")
    if n == 0:
        print("SKIP (no pin)", rel)
        continue
    io.open(p, "w", encoding="utf-8", newline="").write(new)
    changed.append(rel)
    print("PATCHED", rel, f"({n} pin(s))")

# 5. stale py pins 2.58.57 -> 2.58.62 (pre-existing reds from review, closed by sweep)
stale_pins = [
    "tests/test_webapp_design_tokens_round1025.py",
    "tests/test_webapp_f6_round1025.py",
    "tests/test_webapp_hotfix6_round1025.py",
]
for rel in stale_pins:
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    raw = io.open(p, "r", encoding="utf-8", newline="").read()
    n = raw.count("2.58.57")
    new = raw.replace("2.58.57", "2.58.62")
    if n == 0:
        print("SKIP (no pin)", rel)
        continue
    io.open(p, "w", encoding="utf-8", newline="").write(new)
    changed.append(rel)
    print("PATCHED", rel, f"({n} stale 2.58.57 pin(s))")

# 6. JS hotfix harness pins (regex literals 2\.58\.61 -> 2\.58\.62)
js_pins = [
    "tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js",
    "tests/js/round1025_hotfix8_shell_aurora_test.js",
    "tests/js/round1025_hotfix9_shell_flex_glass_aurora_test.js",
    "tests/js/round1025_hotfix10_glass_geometry_bg_test.js",
]
for rel in js_pins:
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    raw = io.open(p, "r", encoding="utf-8", newline="").read()
    n = raw.count('2\\.58\\.61')
    new = raw.replace('2\\.58\\.61', '2\\.58\\.62')
    if n == 0:
        print("SKIP (no pin)", rel)
        continue
    io.open(p, "w", encoding="utf-8", newline="").write(new)
    changed.append(rel)
    print("PATCHED", rel, f"({n} js-pin(s))")

# 7. sanity: no stray pins left in pin files
leftover = 0
for rel in py_pins + stale_pins + js_pins:
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    raw = io.open(p, "r", encoding="utf-8", newline="").read()
    if '2\\.58\\.61' in raw:
        print("LEFTOVER-JS-61", rel); leftover += 1
    if '2.58.61' in raw:
        print("LEFTOVER-PY-61", rel); leftover += 1
    if '2.58.57' in raw and rel in stale_pins:
        print("LEFTOVER-PY-57", rel); leftover += 1

print()
print("total changed:", len(changed), "| leftovers:", leftover)
