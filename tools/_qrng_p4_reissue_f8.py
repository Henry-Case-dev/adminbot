# -*- coding: utf-8 -*-
"""F8-переиздание после QRNG P4 — отдельная config-вкладка «Случайность».

QRNG P4 (17.11.2026, arch D4/§9 поручения): TAB_MOD_RANDOM + TAB_RULES 22→23;
memory_random перенесена с mod_sleep, keys_random — с llm_providers. Состав
REGISTRY/GROUPS/_TAB_BY_GROUP НЕ меняется (648/121/119, delta 247), но
group_tab для двух групп и счётчик TAB_RULES меняются — baseline обязан
отражать фактический каталог.

Запуск: .venv\\Scripts\\python.exe tools/_qrng_p4_reissue_f8.py
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tools.gen_param_registry_round1025 as gen  # noqa: E402
from services import param_catalog as pc  # noqa: E402


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def _write_json_crlf(path: Path, data: dict) -> None:
    """Сохранять JSON, сохраняя CRLF-окончания файла (min diff)."""
    raw = path.read_bytes() if path.exists() else b""
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if b"\r\n" in raw:
        text = text.replace("\n", "\r\n")
    path.write_bytes((text + ("\r\n" if b"\r\n" in raw or not raw else "\n"))
                     .encode("utf-8"))


rc = gen.run_emit()
if rc != 0:
    raise SystemExit("EMIT FAILED")
rows = gen.build_rows()
delta = sum(1 for r in rows if r["status"] == "new")
catalog_sha = sha("services/param_catalog.py")

_NOTE = (
    "; QRNG P4 (17.11.2026, arch D4/§9): +1 config-вкладка mod_random "
    "«Случайность» (TAB_RULES/TAB_NAV/TITLES 22→23); memory_random перенесена "
    "с mod_sleep, keys_random — с llm_providers (перенос, не копия). Состав "
    "REGISTRY/GROUPS/_TAB_BY_GROUP не менялся (648/121/119, delta %d)."
    % delta
)

fx_path = ROOT / "tests/fixtures/round1025/f8_baseline.json"
fx = json.loads(fx_path.read_text(encoding="utf-8"))
fx["counts"]["REGISTRY"] = len(pc.REGISTRY)
fx["counts"]["GROUPS"] = len(pc.GROUPS)
fx["counts"]["TAB_BY_GROUP"] = len(pc._TAB_BY_GROUP)
fx["counts"]["_TAB_BY_GROUP"] = len(pc._TAB_BY_GROUP)
fx["counts"]["TAB_RULES"] = len(pc.TAB_RULES)
fx["counts"]["delta"] = delta
fx["sha256"] = catalog_sha
if "QRNG P4" not in fx.get("_provenance_note", ""):
    fx["_provenance_note"] = fx.get("_provenance_note", "") + _NOTE
if "QRNG P4" not in fx.get("superseded_by", ""):
    fx["superseded_by"] = fx.get("superseded_by", "") + _NOTE
_write_json_crlf(fx_path, fx)
print("f8_baseline updated:", fx["counts"], "routes:", len(fx["routes"]))

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
provenance = cb.get("_provenance") or {}
if isinstance(provenance, dict) and "QRNG P4" not in str(
        provenance.get("note", "")):
    provenance["note"] = str(provenance.get("note", "")) + " | " + _NOTE
    cb["_provenance"] = provenance
_write_json_crlf(cb_path, cb)
print("catalog_baseline keys:", len(cb["registry_keys"]))

# QRNG P4: каталог-производная фикстура ключей страницы «Случайность».
# Нужна JS-тесту F5, чтобы новый ключ в memory_random/keys_random не осиротел
# молча: страница обязана отрендерить ВСЕ ключи групп, кроме hidden и
# read-only master (memory.random_enabled).
qrng_path = ROOT / "tests/fixtures/qrng_p4_random_keys.json"
qrng_groups = {}
for gid in ("memory_random", "keys_random"):
    qrng_groups[gid] = sorted(
        s.pg_key for s in pc.REGISTRY.values()
        if s.group == gid and not s.hidden
        and s.pg_key != "memory.random_enabled")
qrng_data = {
    "groups": qrng_groups,
    "master": "memory.random_enabled",
    "page_keys": sorted({k for keys in qrng_groups.values() for k in keys}),
}
_write_json_crlf(qrng_path, qrng_data)
print("qrng_p4_random_keys:", len(qrng_data["page_keys"]))

# Пин sha256 followed-up каталога (единственный прямой hash-пин).
changed = 0
for path in sorted((ROOT / "tests").glob("*.py")):
    raw = path.read_bytes()
    text = raw.decode("utf-8")
    new = re.sub(
        r"(PARAM_CATALOG_SHA256_FOLLOWUP = \(\s*\")[0-9a-f]{64}(\")",
        r"\g<1>%s\g<2>" % catalog_sha, text)
    if new != text:
        path.write_bytes(new.encode("utf-8"))
        changed += 1
print("sha-pin files updated:", changed)
print("param_catalog sha256 =", catalog_sha)
print("REGISTRY:", len(pc.REGISTRY), "delta:", delta,
      "TAB_RULES:", len(pc.TAB_RULES))
