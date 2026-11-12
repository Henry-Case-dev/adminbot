import json
import re
from pathlib import Path

base = Path(r"C:\Code\Python\adminbot\plans\features\self-diag-01\release-258198")


def failures(path: Path) -> list[str]:
    # Some log lines are hard-wrapped at 120 chars (PowerShell Tee-Object), so
    # test ids are reassembled by dropping line breaks before matching.
    text = path.read_text(encoding="utf-8", errors="replace").replace("\r\n", "")
    text = text.replace("\n", "")
    return sorted(set(re.findall(r"FAILED (tests/[^\s]+)", text)))


b = failures(base / "baseline-web-wide-25876167.log")
c = failures(base / "candidate-web-wide-258198.log")
data = {
    "release": "2.58.198",
    "candidate_code": "454727ede7a2577b80dbef1b5d9c1ce3c4a3342d",
    "release_branch_sha": "78982058119763b89fbf8e5f01cd376dfecab2c6",
    "base_sha": "2587616759de31283585ffc105c91e7193c2e89e",
    "verdict": "BLOCKED_PREFLIGHT",
    "deployed": False,
    "web_wide": {"baseline_failed": len(b), "candidate_failed": len(c),
                 "baseline": b, "candidate": c,
                 "new": [x for x in c if x not in b],
                 "fixed": [x for x in b if x not in c]},
    "js_unit": {"baseline": "45 passed",
                "candidate": "44 passed, 1 failed",
                "failed": ["tests/test_webapp_js_unit.py::test_js_unit_round1025_hotfix6_lens_heartbeat_shell"]},
    "findings": [
        {
            "id": "F1",
            "test": "tests/test_webapp_js_unit.py::test_js_unit_round1025_hotfix6_lens_heartbeat_shell",
            "file": "tests/js/round1025_hotfix6_lens_heartbeat_shell_test.js:200-204",
            "cause": "inserted loadSelfDiagnosis (web/app.js:29909) inside the [_hbDraw..loadStatus] guard slice",
            "class": "test-contract scope (candidate-introduced)",
            "product_impact": "none: _hbDraw unchanged and network-free; loader called only from the refresh button",
            "owner": "Builder (+ Reviewer for the test contract)",
            "minimal_fix": "bound the slice to the _hbDraw body (end at the next method key); keep assertion"
        },
        {
            "id": "F2",
            "test": "tests/test_webapp_round109_ui.py::TestDescriptions::test_no_forbidden_jargon",
            "file": "services/param_catalog.py:4100-4104",
            "cause": "description of flags.self_diag_repo_origin contains the forbidden token 'URL'",
            "class": "owner-visible UI text defect (candidate-introduced)",
            "product_impact": "settings description uses forbidden jargon",
            "owner": "Builder",
            "minimal_fix": "reword without forbidden substrings; sanctioned F8 re-pin of PARAM_CATALOG_SHA256_FOLLOWUP + tools/gen_param_registry_round1025.py --check"
        },
        {
            "id": "F3",
            "test": "tests/test_webapp_evol_w14_states.py::TestUnifiedCheckboxes::test_every_native_checkbox_is_a_design_system_control",
            "file": "web/index.html:987",
            "cause": "new diagnostics matrix renders a bare <input type=checkbox> outside ctl-check/ctl-toggle",
            "class": "UI design-system defect (candidate-introduced)",
            "product_impact": "unstyled native checkbox in the new matrix",
            "owner": "Builder (+ Reviewer visual check)",
            "minimal_fix": "use the design-system control markup (ctl-check/ctl-check__box)"
        }
    ],
    "production": {"untouched": True, "ssh_logins": 0,
                   "healthz": {"status": "ok", "version": "2.58.197"},
                   "rollback_needed": False},
}
target = base / "blocked-findings.json"
target.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
print(target)
print("base_failed", len(b), "candidate_failed", len(c), "new", data["web_wide"]["new"], "fixed", data["web_wide"]["fixed"])
