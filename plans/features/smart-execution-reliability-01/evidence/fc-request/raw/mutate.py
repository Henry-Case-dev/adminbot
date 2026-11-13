"""S13 falsification: apply small semantic mutations, observe specific test
failures, restore from git. Usage: python mutate.py <repo> <logdir>"""
import json
import subprocess
import sys

repo, logdir = sys.argv[1], sys.argv[2]
PY = r"C:\Code\Python\adminbot\.venv\Scripts\python.exe"

MUTATIONS = [
    ("M1_cache_ignores_subject",
     "services/factcheck_context.py",
     '        # S13: фактический предмет входит в идентичность кэша среза.\n'
     '        "subject": _claim_digest(claim_text),\n',
     "",
     ["TestCacheIdentity", "TestCacheRoundTrip"]),
    ("M2_claim_units_drops_subject_remainder",
     "services/factcheck_planner.py",
     "    else:\n"
     "        # S13 §4.1: предмет может содержать условие/вопрос пользователя,\n"
     "        # которых нет в claim_items. Они — часть УЖЕ установленного предмета и\n"
     "        # не должны исчезать из плана только потому, что item-фильтр принял\n"
     "        # лишь material-часть. Остаток предмета добавляется структурно\n"
     "        # (предложения), без лексических правил и новых категорий.\n"
     "        covered = [u.lower() for u in units]\n"
     "        for sentence in sentences:\n"
     "            low = sentence.lower()\n"
     "            if low == claim_low:\n"
     "                continue\n"
     "            if any(low in c or c in low for c in covered):\n"
     "                continue\n"
     "            units.append(sentence)\n"
     "            covered.append(low)\n",
     "",
     ["TestClaimUnits", "TestScenarioDCondition"]),
    ("M3_envelope_ignores_subject_text",
     "services/temporal_factcheck.py",
     '    claim_text = subject_text or (ref.claim_text or "").strip()',
     '    claim_text = (ref.claim_text or "").strip()',
     ["TestScenarioCNarrowing", "TestScenarioEStandaloneQuestion",
      "TestStageConsistency"]),
    ("M4_material_date_transferred_to_question",
     "services/temporal_factcheck.py",
     '    if subject_origin == "request":\n'
     '        original_published_at = None\n'
     '        date_source = "unknown"\n'
     '        date_precision = "unknown"\n',
     "",
     ["TestScenarioEStandaloneQuestion"]),
    ("M5_question_signed_to_material_author",
     "services/temporal_factcheck.py",
     '    if subject is not None and subject_origin == "request":\n'
     '        # Автор самостоятельного вопроса — пользователь; чужой материал не\n'
     '        # становится цитатой автора вопроса и наоборот.\n'
     '        attribution = ({**(dict(ref.attribution) or {}),\n'
     '                        **({"author": request_author} if request_author else {})}\n'
     '                       if request_author else dict(ref.attribution))\n'
     "    else:\n"
     "        attribution = dict(ref.attribution) or _attribution_from_row(row)\n",
     '    attribution = dict(ref.attribution) or _attribution_from_row(row)\n',
     ["TestScenarioEStandaloneQuestion"]),
]

results = []
for name, path, old, new, expect in MUTATIONS:
    full = f"{repo}/{path}"
    text = open(full, encoding="utf-8").read()
    if old not in text:
        results.append({"mutation": name, "status": "PATTERN_NOT_FOUND"})
        continue
    open(full, "w", encoding="utf-8", newline="\n").write(text.replace(old, new, 1))
    try:
        proc = subprocess.run(
            [PY, "-m", "pytest", "tests/test_factcheck_subject_contract.py",
             "-q", "--no-header", "-p", "no:cacheprovider"],
            cwd=repo, capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=300)
        out = (proc.stdout or "") + (proc.stderr or "")
        failed = sorted({ln.split("::", 1)[1].split(" ")[0]
                         for ln in out.splitlines()
                         if ln.startswith("FAILED ")})
        hit = sorted({f for f in failed if any(e in f for e in expect)})
        results.append({
            "mutation": name,
            "status": "KILLED" if hit else "SURVIVED",
            "expected_groups": expect,
            "failing_tests": failed,
            "expected_failures_observed": hit,
            "summary": [ln for ln in out.splitlines() if "passed" in ln or "failed" in ln][-1:],
        })
        open(f"{logdir}/mutation-{name}.txt", "w", encoding="utf-8").write(out)
    finally:
        subprocess.run(["git", "-C", repo, "checkout", "--", path], check=True)

open(f"{logdir}/mutations.json", "w", encoding="utf-8").write(
    json.dumps(results, ensure_ascii=False, indent=1))
for row in results:
    print(row["mutation"], row["status"], len(row.get("expected_failures_observed") or []))
