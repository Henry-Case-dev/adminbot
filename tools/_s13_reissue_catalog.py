# -*- coding: utf-8 -*-
"""SMART-EXECUTION-RELIABILITY-01 §S13: переиздание F8-артефактов каталога.

Прецедент: `tools/_vmq_mem_time_reissue_catalog.py`,
`tools/_asap5_w2_reissue_f8.py`.

Δ каталога: +1 PG-only промпт-ключ `prompts.factcheck_subject_system_prompt`
(группа `prompts_factcheck`, вкладка `prompts`, стадия `synthesizer`).
Причина: рантайм читает ключ через `resolve_prompt`
(`services/factcheck_orchestrator`), но записи каталога не было — `/api/config`
отбивал правку как неизвестный ключ, Prompt Library его не рендерила
(тот же класс дефекта, что SOUL-1 mobile-prompts +1). GROUPS/TAB_BY_GROUP/
TAB_RULES/routes без изменений: REGISTRY 644→645, delta 243→244.

Шаги (как в прецеденте):
  1) регенерация TSV/meta/screen-map/widget-map (`gen_param_registry_round1025`);
  2) fixtures `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`;
  3) пины счётчиков/хэша каталога в тестах.
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tools.gen_param_registry_round1025 as gen  # noqa: E402


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def _write_json_crlf(path: Path, data: dict) -> None:
    raw = path.read_bytes()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if b"\r\n" in raw:
        text = text.replace("\n", "\r\n")
    path.write_bytes((text + ("\r\n" if b"\r\n" in raw else "\n"))
                     .encode("utf-8"))


_NOTE = (
    "; SMART-EXECUTION-RELIABILITY-01 §S13 (14.11.2026): санкционированная "
    "Δ каталога +1 PG-only промпт-ключ prompts.factcheck_subject_system_prompt "
    "(группа prompts_factcheck, стадия synthesizer; рантайм читал ключ, но "
    "записи каталога не было — /api/config отбивал правку как неизвестный "
    "ключ) → REGISTRY 644→645, delta 243→244 (inventory 411 не менялся); "
    "GROUPS/_TAB_BY_GROUP/TAB_RULES/routes без изменений."
)

rc = gen.run_emit()
if rc != 0:
    raise SystemExit("EMIT FAILED")

from services import param_catalog as pc  # noqa: E402

print("REGISTRY:", len(pc.REGISTRY), "delta:",
      len([r for r in gen.build_rows() if r["status"] == "new"]))

fx_path = ROOT / "tests/fixtures/round1025/f8_baseline.json"
fx = json.loads(fx_path.read_text(encoding="utf-8"))
fx["counts"]["REGISTRY"] = len(pc.REGISTRY)
fx["counts"]["GROUPS"] = len(pc.GROUPS)
fx["counts"]["TAB_BY_GROUP"] = len(pc._TAB_BY_GROUP)
fx["counts"]["_TAB_BY_GROUP"] = len(pc._TAB_BY_GROUP)
fx["counts"]["TAB_RULES"] = len(pc.TAB_RULES)
fx["counts"]["delta"] = len([r for r in gen.build_rows()
                            if r["status"] == "new"])
if isinstance(fx.get("sha256"), dict):
    fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
else:
    fx["sha256"] = sha("services/param_catalog.py")
blob = "\n".join((ROOT / p).read_text(encoding="utf-8")
                 for p in fx["artifacts"])
fx["sha256_artifacts"] = hashlib.sha256(blob.encode("utf-8")).hexdigest()
if _NOTE.strip() not in fx.get("superseded_by", ""):
    fx["superseded_by"] = fx.get("superseded_by", "") + _NOTE
_write_json_crlf(fx_path, fx)
print("f8_baseline:", fx["counts"])

cb_path = ROOT / "tests/fixtures/round1025/catalog_baseline.json"
cb = json.loads(cb_path.read_text(encoding="utf-8"))
cb["registry_keys"] = sorted(pc.REGISTRY.keys())
cb["group_ids"] = sorted(g.id for g in pc.GROUPS)
cb["group_tab"] = {gid: pc.group_tab(gid)
                   for gid in sorted(g.id for g in pc.GROUPS)}
cb["tab_nav"] = {tid: pc.tab_nav(tid)
                 for tid in sorted(set(cb["tab_nav"]) | set(pc.TAB_NAV))}
cb["counts"] = {"REGISTRY": len(pc.REGISTRY), "GROUPS": len(pc.GROUPS),
                "_TAB_BY_GROUP": len(pc._TAB_BY_GROUP),
                "TAB_RULES": len(pc.TAB_RULES)}
cb["_provenance"]["note"] = (
    cb["_provenance"].get("note", "") + _NOTE)
_write_json_crlf(cb_path, cb)
print("catalog_baseline keys:", len(cb["registry_keys"]), cb["counts"])

_REPLACEMENTS = (
    (r"len\(pc\.REGISTRY\) == 644", "len(pc.REGISTRY) == 645"),
    (r"len\(REGISTRY\) == 644", "len(REGISTRY) == 645"),
    (r"len\(tsv\) - 1 == 644", "len(tsv) - 1 == 645"),
    # Заодно снят off-by-one: артефакт содержит header + REGISTRY строк.
    (r"assert len\(tsv\) == 644", "assert len(tsv) - 1 == 645"),
    (r"len\(rows\) == 644", "len(rows) == 645"),
    (r"len\(keys\) == 644", "len(keys) == 645"),
    (r"\[\"counts\"\]\[\"REGISTRY\"\] == 644",
     "[\"counts\"][\"REGISTRY\"] == 645"),
    (r"\[\"counts\"\]\[\"delta\"\] == 243",
     "[\"counts\"][\"delta\"] == 244"),
    (r"\"644\" in meta and \"411\" in meta and \"243\" in meta",
     "\"645\" in meta and \"411\" in meta and \"244\" in meta"),
    (r"PARAM_CATALOG_SHA256_FOLLOWUP = \(\n    \"[0-9a-f]{64}\"\)",
     "PARAM_CATALOG_SHA256_FOLLOWUP = (\n    \"%s\")"
     % sha("services/param_catalog.py")),
)
changed = 0
for path in sorted((ROOT / "tests").glob("*.py")):
    # Байтовое чтение/запись: сохраняет существующие LF/CRLF каждого файла
    # (precedent: ошибочный `write_text` переписывал LF→CRLF всей волной).
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    new = text
    for pat, repl in _REPLACEMENTS:
        new = re.sub(pat, repl, new)
    if new != text:
        path.write_bytes(new.encode("utf-8"))
        changed += 1
        print("pins:", path.name)
print("files changed:", changed)
