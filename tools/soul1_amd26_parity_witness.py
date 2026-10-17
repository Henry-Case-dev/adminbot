"""AMD26 — паритет осей OFF и отпечатки файлов слайса.

1) С флагами OFF (по умолчанию) шов `authorial_system` возвращает прежний
   канон байт-в-байт и пустой манифест (новый слой не рендерится);
2) sha256_12 изменённых/новых файлов слайса AMD26.

Запуск: `py -3 tools/soul1_amd26_parity_witness.py`
Выход: `plans/features/soul-1/evidence/amd26/parity-off.json`
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))
OUT = (REPO / "plans" / "features" / "soul-1" / "evidence" / "amd26"
       / "parity-off.json")

FILES = (
    "services/lore_compiler_service.py",
    "services/prompt_registry.py",
    "services/mca_authorial_speech.py",
    "services/lore_prompts.py",
    "tests/test_soul1_amd26_authorial_wiring.py",
    "tests/test_soul1_w4_authorial_genre.py",
    "tools/soul1_amd26_mutation_witness.py",
    "tools/soul1_amd26_parity_witness.py",
)

CANON = "КАНОН-ЛЕТОПИСЦА-БАЙТ-В-БАЙТ"


def sha12(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


def main() -> int:
    for key in ("UNIFIED_COMPOSER_ENABLED", "HUMOR_CRAFT_ENABLED",
                "HUMOR_LIBRARY_ENABLED", "HUMOR_FEEDBACK_ENABLED",
                "HUMOR_CANDIDATE_EVAL_ENABLED"):
        os.environ.pop(key, None)

    from services import mca_gates as gates
    from services import mca_authorial_speech as au
    from services import prompt_composer as pc

    gates_off = pc.gates_from_config()
    seam_text, seam_manifest = asyncio.run(au.authorial_system(
        chat_id=-100500, writer="lore_writer", genre="lore",
        legacy_canon=CANON, channel="plain", html_safe=True))

    report = {
        "slice": "soul-1/AMD26",
        "flags_default": {
            "unified_composer_enabled": gates_off.unified_composer_enabled,
            "humor_craft_enabled": gates_off.humor_craft_enabled,
            "humor_library_enabled": gates_off.humor_library_enabled,
            "humor_feedback_enabled": gates_off.humor_feedback_enabled,
        },
        "env_gates_default": {
            "UNIFIED_COMPOSER_ENABLED": gates.unified_composer_env_enabled(),
        },
        "authorial_seam_off": {
            "text_is_canon_byte_for_byte": seam_text == CANON,
            "manifest_is_none": seam_manifest is None,
            "chars": len(seam_text),
        },
        "no_new_layer_rendered": (seam_text == CANON
                                  and seam_manifest is None),
        "fingerprints_sha256_12": {rel: sha12(REPO / rel) for rel in FILES},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1),
                   encoding="utf-8", newline="\n")
    print("flags:", report["flags_default"], report["env_gates_default"])
    print("seam OFF:", report["authorial_seam_off"])
    for rel, digest in report["fingerprints_sha256_12"].items():
        print("  %s  %s" % (digest, rel))
    return 0 if report["no_new_layer_rendered"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
