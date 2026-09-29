# -*- coding: utf-8 -*-
"""ASAP-3 rework round 1: пересчёт Working-Tree-Hash (рецепт review.md).

Манифест: sorted(path + ':' + file_sha256), WTH = sha256 манифеста.
Состав (41 запись, задокументирован в evidence.md §Rework):
  35 кода/доков (ASAP-3-скоуп + 2 пина чужих дельт) + 3 файла плана фичи
  (spec/adr/tasks) + 3 файла artifacts/ (2 скриншота Reviewer + desktop
  Builder). ИСКЛЮЧЕНЫ само-ссылочные/раунд-артефакты: review.md (артефакт
  review — прецедент исходного WTH), evidence.md и wth-манифест json
  (значение WTH публикуется ВНИТРИ evidence.md — включать их в манифест
  технически невозможно без парадокса фиксации).
"""
import hashlib
import json
from pathlib import Path

ROOT = Path(".")

FILES = [
    # ── новые модули/тесты фичи (8) ──
    "services/model_capacity.py",
    "services/direct_context_composer.py",
    "tests/test_direct_context_capacity_asap3.py",
    "tests/test_direct_context_composer_asap3.py",
    "tests/test_direct_context_scenarios_asap3.py",
    "tests/test_direct_decision_matrix_asap3.py",
    "tests/js/round1028_asap3_direct_context_test.js",
    "tools/_asap3_webapp_dev.py",
    # ── изменённые ядро/веб (8) ──
    "config/settings.py",
    "services/agentic_events.py",
    "services/smartmodule_utils.py",
    "services/param_catalog.py",
    "web/app.js",
    "tests/conftest.py",
    "pytest.ini",
    "README.md",
    # ── F8-артефакты (5) ──
    "plans/docs/param-registry-round1025.tsv",
    "plans/docs/param-registry-round1025.meta.md",
    "plans/docs/screen-map-round1025.md",
    "tests/fixtures/round1025/f8_baseline.json",
    "tests/fixtures/round1025/catalog_baseline.json",
    # ── пин-тесты прошлых раундов (9) + пины чужих дельт (2) ──
    "tests/test_param_catalog.py",
    "tests/test_round1025_f8_registry.py",
    "tests/test_decision_making_round1026.py",
    "tests/test_agentic_events_round1026.py",
    "tests/test_telegram_reactions_round1026.py",
    "tests/js/round1025_hotfix7_shell_glass_heartbeat_test.js",
    "tests/js/round1025_hotfix8_shell_aurora_test.js",
    "tests/js/round1025_hotfix9_shell_flex_glass_aurora_test.js",
    "tests/js/round1025_hotfix10_glass_geometry_bg_test.js",
    "tests/test_direct_chat.py",
    "tests/test_tool_coordinator_round1026.py",
    # ── СМЕШАННЫЕ с чужим WIP (3) ──
    "services/direct_chat_service.py",
    "web/index.html",
    "web/api/routes.py",
    # ── план фичи (3; evidence.md/review.md вне манифеста — само-ссылка) ──
    "plans/features/mca-asap3-direct-context-reply-reliability/spec.md",
    "plans/features/mca-asap3-direct-context-reply-reliability/"
    "adr-1028-2-direct-context-composer-and-decision-matrix.md",
    "plans/features/mca-asap3-direct-context-reply-reliability/tasks.md",
    # ── artifacts (3: 2 Reviewer + desktop Builder) ──
    "plans/features/mca-asap3-direct-context-reply-reliability/artifacts/"
    "asap3_reviewer_desktop_1280_direct_context.png",
    "plans/features/mca-asap3-direct-context-reply-reliability/artifacts/"
    "asap3_reviewer_mobile_390_direct_context.png",
    "plans/features/mca-asap3-direct-context-reply-reliability/artifacts/"
    "browser_desktop_1280.png",
]

manifest = []
missing = []
for rel in sorted(FILES):
    p = ROOT / rel
    if not p.exists():
        missing.append(rel)
        continue
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    manifest.append("%s:%s" % (rel.replace("\\", "/"), sha))

wth = hashlib.sha256("\n".join(manifest).encode("utf-8")).hexdigest()
out = {
    "recipe": "sha256 of sorted(path + ':' + file_sha256) manifest",
    "entries": len(manifest),
    "missing": missing,
    "wth": wth,
    "files": {rel.replace("\\", "/"): hashlib.sha256(
        (ROOT / rel).read_bytes()).hexdigest()
        for rel in sorted(FILES) if (ROOT / rel).exists()},
}
Path_ = Path("plans/features/mca-asap3-direct-context-reply-reliability/"
             "artifacts/wth_manifest_rework1.json")
Path_.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                 encoding="utf-8")
print("entries=%d wth=%s" % (len(manifest), wth))
if missing:
    print("MISSING:", missing)
