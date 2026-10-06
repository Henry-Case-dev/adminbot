# -*- coding: utf-8 -*-
"""T-5150 deploy: release bump 2.58.63 -> 2.58.64 per repo convention (_t5126_release_bump.py precedent).
Touches: APP_VERSION (config/settings.py), README.md version header,
F8 meta pin (plans/docs/param-registry-round1025.meta.md),
23 py release-pin test files, 4 JS hotfix harness pin regexes.
Byte-safe (newline-preserving). Historical OFF-parity mentions in services docstrings unchanged.
"""
import io
import os

ROOT = r"C:\Code\Python\adminbot"
OLD, NEW = "2.58.63", "2.58.64"
errors = []

def patch(rel, expected_counts=None):
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    with io.open(p, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8")
    n = text.count(OLD)
    if n == 0:
        errors.append(f"NO-PIN {rel}")
        print("NO-PIN", rel)
        return
    if expected_counts is not None and n != expected_counts:
        errors.append(f"COUNT {rel}: {n} != {expected_counts}")
        print("COUNT-MISMATCH", rel, n)
        return
    text2 = text.replace(OLD, NEW)
    with io.open(p, "wb") as f:
        f.write(text2.encode("utf-8"))
    print("PATCHED", rel, f"({n})")

# 1. APP_VERSION (exactly 1 pin; other 2.58.63 mentions in settings.py are OFF-parity docstrings)
p = os.path.join(ROOT, "config", "settings.py")
with io.open(p, "rb") as f:
    raw = f.read()
text = raw.decode("utf-8")
needle_old = 'APP_VERSION = "2.58.63"'
needle_new = 'APP_VERSION = "2.58.64"'
cnt = text.count(needle_old)
assert cnt == 1, f"APP_VERSION pin count {cnt}"
text = text.replace(needle_old, needle_new, 1)
with io.open(p, "wb") as f:
    f.write(text.encode("utf-8"))
print("PATCHED config/settings.py APP_VERSION")

# 2. README header
p = os.path.join(ROOT, "README.md")
with io.open(p, "rb") as f:
    raw = f.read()
text = raw.decode("utf-8")
needle_old = "**Версия:** v2.58.63"
needle_new = "**Версия:** v2.58.64"
cnt = text.count(needle_old)
assert cnt == 1, f"README header count {cnt}"
text = text.replace(needle_old, needle_new, 1)
with io.open(p, "wb") as f:
    f.write(text.encode("utf-8"))
print("PATCHED README.md header")

# 3. F8 meta pin
p = os.path.join(ROOT, "plans", "docs", "param-registry-round1025.meta.md")
with io.open(p, "rb") as f:
    raw = f.read()
text = raw.decode("utf-8")
needle_old = "- **APP_VERSION:** `2.58.63`"
needle_new = "- **APP_VERSION:** `2.58.64`"
cnt = text.count(needle_old)
assert cnt == 1, f"F8 meta pin count {cnt}"
text = text.replace(needle_old, needle_new, 1)
with io.open(p, "wb") as f:
    f.write(text.encode("utf-8"))
print("PATCHED plans/docs/param-registry-round1025.meta.md F8 meta-pin")

# 4. py release pins (23 files; polygon has 2 pins)
py_pins = [
    "tests/test_decision_making_round1026.py",
    "tests/test_image_context_memory_round1026.py",
    "tests/test_round1025_f8_registry.py",
    "tests/test_scope_selector_round1025.py",
    "tests/test_summary_deploy_round1026.py",
    "tests/test_summary_fact_package.py",
    "tests/test_summary_logging_runid.py",
    "tests/test_summary_publish_integration_round1026.py",
    "tests/test_summary_test_run.py",
    "tests/test_telegram_reactions_round1026.py",
    "tests/test_tool_coordinator_round1026.py",
    "tests/test_unified_image_request_round1026.py",
    "tests/test_webapp_design_tokens_round1025.py",
    "tests/test_webapp_f11_round1025.py",
    "tests/test_webapp_f6_round1025.py",
    "tests/test_webapp_f7_round1025.py",
    "tests/test_webapp_f9_round1025.py",
    "tests/test_webapp_hotfix10_round1025.py",
    "tests/test_webapp_hotfix6_round1025.py",
    "tests/test_webapp_hotfix7_round1025.py",
    "tests/test_webapp_hotfix8_round1025.py",
    "tests/test_webapp_hotfix9_round1025.py",
    "tests/test_webapp_round1026_polygon.py",
]
for rel in py_pins:
    patch(rel)

# 5. js harness pins (4 files)
js_pins = [
    "tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js",
    "tests/js/round1025_hotfix8_shell_aurora_test.js",
    "tests/js/round1025_hotfix9_shell_flex_glass_aurora_test.js",
    "tests/js/round1025_hotfix10_glass_geometry_bg_test.js",
]
for rel in js_pins:
    p = os.path.join(ROOT, rel.replace("/", os.sep))
    with io.open(p, "rb") as f:
        raw = f.read()
    text = raw.decode("utf-8")
    n = text.count("2\\.58\\.63")
    if n == 0:
        errors.append(f"NO-JS-PIN {rel}")
        print("NO-JS-PIN", rel)
        continue
    text = text.replace("2\\.58\\.63", "2\\.58\\.64")
    with io.open(p, "wb") as f:
        f.write(text.encode("utf-8"))
    print("PATCHED", rel, f"({n})")

print("---")
if errors:
    print("ERRORS:")
    for e in errors:
        print(" ", e)
else:
    print("SWEEP OK: 29 files")
