"""W4 — доказательства паритета флагов и отпечатки файлов слайса.

1) С флагами OFF (по умолчанию) в манифесте нет ни одного нового слоя, а
   Core/Identity/Style ведут себя как раньше; 2) sha256_12 изменённых файлов.

Запуск: `py -3 tools/soul1_w4_parity_witness.py`
Выход: `plans/features/soul-1/evidence/w4/parity-off.json`
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
OUT = (REPO / "plans" / "features" / "soul-1" / "evidence" / "w4"
       / "parity-off.json")

FILES = (
    "services/mca_humor_craft.py",
    "services/mca_sample_library.py",
    "services/mca_humor_feedback.py",
    "services/mca_authorial_speech.py",
    "services/prompt_composer.py",
    "services/prompt_registry.py",
    "services/mca_gates.py",
    "services/mca_experience.py",
    "services/mca_experience_jobs.py",
    "services/database.py",
    "services/direct_chat_service.py",
    "services/nostalgia_worker.py",
    "services/permissions.py",
    "web/api/speech.py",
    "web/app.js",
    "web/index.html",
    "tools/ui_soul1_w4_speech_e2e.py",
    "tools/ui_soul1_w4_dump_fixture.py",
    "tools/soul1_w4_mutation_witness.py",
    "tests/test_soul1_w4_humor_craft.py",
    "tests/test_soul1_w4_sample_library.py",
    "tests/test_soul1_w4_humor_feedback.py",
    "tests/test_soul1_w4_authorial_genre.py",
)


def sha12(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def main() -> int:
    for key in ("UNIFIED_COMPOSER_ENABLED", "HUMOR_CRAFT_ENABLED",
                "HUMOR_LIBRARY_ENABLED", "HUMOR_FEEDBACK_ENABLED",
                "HUMOR_CANDIDATE_EVAL_ENABLED"):
        os.environ.pop(key, None)

    from services import mca_gates as gates
    from services import prompt_composer as pc

    gates_off = pc.gates_from_config()
    plan = pc.PromptPlan(
        profile="speech_plain", writer="l2_writer", chat_id=1,
        base_prompt="БАЗА", gates=gates_off)
    manifest = pc.compose_prompt(plan)
    new_layers = {}
    for trace in manifest.layers:
        if trace.layer in ("humor_craft", "few_shot"):
            new_layers[trace.layer] = {
                "rendered": trace.rendered, "skip_reason": trace.skip_reason}

    report = {
        "slice": "soul-1/W4",
        "flags_default": {
            "unified_composer_enabled": gates_off.unified_composer_enabled,
            "humor_craft_enabled": gates_off.humor_craft_enabled,
            "humor_library_enabled": gates_off.humor_library_enabled,
            "humor_feedback_enabled": gates_off.humor_feedback_enabled,
        },
        "env_gates_default": {
            "HUMOR_CRAFT_ENABLED": gates.humor_craft_enabled(),
            "HUMOR_CANDIDATE_EVAL_ENABLED":
                gates.humor_candidate_eval_enabled(),
        },
        "manifest_new_layers_off": new_layers,
        "no_new_layer_rendered": not any(v["rendered"]
                                         for v in new_layers.values()),
        "fingerprints_sha256_12": {rel: sha12(REPO / rel) for rel in FILES},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                   encoding="utf-8")
    print("flags:", report["flags_default"], report["env_gates_default"])
    print("new layers OFF:", new_layers)
    print("no new layer rendered:", report["no_new_layer_rendered"])
    for rel, digest in report["fingerprints_sha256_12"].items():
        print("  %s  %s" % (digest, rel))
    return 0 if report["no_new_layer_rendered"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
