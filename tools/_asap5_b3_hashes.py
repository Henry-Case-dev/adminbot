# -*- coding: utf-8 -*-
"""ASAP 5 B3: SHA256-манифест дельты лейна (для evidence.md, R17-safe)."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FILES = [
    # ── source (B3 write-scope) ──
    "services/graphrag_rebuild.py",
    "services/summary_memory.py",
    "services/embedding_control_plane.py",
    "services/database.py",
    "services/llm_client.py",
    "services/llm_probe.py",
    "services/status_service.py",
    "services/mca_random_source.py",
    "services/mca_gates.py",
    "services/config_cache.py",
    "services/param_catalog.py",
    "web/app.js",
    "web/index.html",
    # ── tests B3 (новые) ──
    "tests/test_asap5_graphrag_recovery.py",
    "tests/test_asap5_random_bootstrap_config.py",
    "tests/test_asap5_paradigms_diagnostics.py",
    "tests/test_asap5_embedding_identity.py",
    # ── tests (санкционированные обновления пинов/харнесов) ──
    "tests/test_mca06_sleep_bc_round1033.py",
    "tests/test_llm_client.py",
    "tests/test_param_catalog.py",
    "tests/test_mca10a_random_source_block_c_round1037.py",
    "tests/test_mca17c_invariants_round1047.py",
    "tests/test_round1025_f8_registry.py",
    "tests/test_settings_persistence_round1014.py",
    "tests/test_mca19_block_f_round1043.py",
    "tests/js/round1037_random_source_test.js",
    "tests/js/routing_test.js",
    # ── fixtures / F8-артефакты ──
    "tests/fixtures/round1025/f8_baseline.json",
    "tests/fixtures/round1025/catalog_baseline.json",
    "plans/docs/param-registry-round1025.tsv",
    "plans/docs/param-registry-round1025.meta.md",
    "plans/docs/screen-map-round1025.md",
    # ── tools ──
    "tools/_asap5_reissue_f8.py",
    "tools/_asap5_pin_catalog_529.py",
    "tools/_asap5_pin_categorized_504.py",
]
out = {}
for rel in FILES:
    p = ROOT / rel
    out[rel] = hashlib.sha256(p.read_bytes()).hexdigest()
dest = ROOT / "plans/features/asap5-final-fixes/b3_hashes.json"
dest.write_text(json.dumps(out, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8")
for k, v in out.items():
    print(f"{v[:16]}  {k}")
