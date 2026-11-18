"""P0 L1 (2026-11-17): переиздание F8-артефактов каталога.

Δ каталога = 0 (ключи/группы/типы/счётчики не менялись). Изменены ТОЛЬКО
тексты описаний двух существующих ключей: `limits.direct_l1_timeout_seconds`
и `limits.direct_l1_max_output_tokens` — честная подпись «пусто = наследовать
политику/контракт, значение = явный override» вместо утверждений про
15 секунд/512 токенов, которые больше не применяются по умолчанию
(LVS-L1-12/13/14). Прецедент: `tools/_vmq_mem_time_reissue_catalog.py`,
CFG-03 (description-only, хэш переутверждён осознанно, L-F11S-1).
"""
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tools.gen_param_registry_round1025 as gen  # noqa: E402

if gen.run_emit() != 0:
    raise SystemExit("EMIT FAILED")

from services import param_catalog as pc  # noqa: E402

fx_path = ROOT / "tests/fixtures/round1025/f8_baseline.json"
fx = json.loads(fx_path.read_text(encoding="utf-8"))


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


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
_NOTE = (
    "; P0 L1 llm-vision-scheduler-p0 (18.11.2026, LVS-L1-12/13/14): Δ каталога "
    "= 0 (ключи/группы/типы/счётчики не менялись). Изменены только описания "
    "limits.direct_l1_timeout_seconds и limits.direct_l1_max_output_tokens: "
    "15 s / 512 tokens больше не универсальный аварийный fallback, пусто = "
    "наследовать транспорт/контракт плана, значение = явный override владельца. "
    "TSV/meta переэмитированы генератором (--check OK, 645 строк); "
    "хэш переутверждён осознанно (L-F11S-1).")
for key in ("superseded_by", "note"):
    if isinstance(fx.get(key), str):
        fx[key] = fx[key] + _NOTE
        break
else:                                    # pragma: no cover - форма фикстуры
    raise SystemExit("no note field in f8_baseline.json")

raw = fx_path.read_bytes()
text = json.dumps(fx, ensure_ascii=False, indent=2)
if b"\r\n" in raw:
    text = text.replace("\n", "\r\n")
fx_path.write_bytes((text + ("\r\n" if b"\r\n" in raw else "\n")).encode("utf-8"))
print("counts", fx["counts"])
print("sha", fx["sha256_artifacts"][:16])
