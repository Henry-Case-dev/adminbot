# -*- coding: utf-8 -*-
"""Переиздание F8-артефактов для ASAP-VISION-SYNC-01 (волна 2, 31.10.2026).

Методика: `tools/_asap5_reissue_f8.py` / `tools/_mca18_reissue_f8.py`.
Основание: §5/§watchdog текущего ТЗ (каталогизация предела вывода Vision и
границ ожидания/жизни медиа-задачи, чтобы владелец видел и менял значение).

Δ каталога = +12 ParamSpec (PG-only, группы и вкладки НЕ меняются):
  * models (3): `models.vision_max_output_tokens`, `models.vision_reasoning`,
    `models.vision_structured_output` — группа `models_vision`
    (вкладка провайдеров моделей);
  * limits (9): `limits.vision_{readiness_wait,association_window,
    pending_intent_ttl,job_lease,queue_wait,job_lifetime,
    job_max_recoveries,job_backoff_base,job_backoff_max}_seconds
    (job_max_recoveries — без суффикса) — группа `limits_vision`
    (вкладка «Распознавание изображений»).
REGISTRY 583→595; GROUPS 120 (0); `_TAB_BY_GROUP` 118 (0); TAB_RULES 22
in-place; delta 177→189 (новые ключи отсутствуют в inventory 10.14); Settings
— только env ClassVar-дефолты (`VISION_MAX_OUTPUT_TOKENS`, `MCA_VISION_*`),
полей dataclass НЕ добавлено (dataclasses.fields = 468); secret — нет;
routes.py не менялся — `ROUTES_SHA256_F11` не переутверждается.

Шаги:
  1) переиздание TSV/meta/screen-map генератором `gen_param_registry_round1025`;
  2) обновление `tests/fixtures/round1025/{f8_baseline,catalog_baseline}.json`;
  3) синхронизация канон-пинов каталога в тестах (583→595 / 177→189).

Запуск: `.venv\\Scripts\\python.exe tools/_vision_sync_w2_reissue_f8.py`
"""
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import tools.gen_param_registry_round1025 as gen  # noqa: E402

NEW_REGISTRY = 595
NEW_DELTA = 189


def sha(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def _write_json_crlf(path: Path, data: dict) -> None:
    """Аккуратный JSON с сохранением CRLF-стиля исходного файла (min diff)."""
    raw = path.read_bytes()
    text = json.dumps(data, ensure_ascii=False, indent=2)
    if b"\r\n" in raw:
        text = text.replace("\n", "\r\n")
    path.write_bytes((text + ("\r\n" if b"\r\n" in raw else "\n"))
                     .encode("utf-8"))


# Шаг 1) артефакты F8 (TSV/meta/screen-map) -------------------------------
rc = gen.run_emit()
if rc != 0:
    raise SystemExit("EMIT FAILED")

# Шаг 2) fixtures ----------------------------------------------------------
fx_path = ROOT / "tests/fixtures/round1025/f8_baseline.json"
fx = json.loads(fx_path.read_text(encoding="utf-8"))
fx["counts"]["REGISTRY"] = NEW_REGISTRY
fx["counts"]["delta"] = NEW_DELTA
fx["sha256"]["services/param_catalog.py"] = sha("services/param_catalog.py")
fx["sha256"]["web/api/routes.py"] = sha("web/api/routes.py")
routes_txt = (ROOT / "web/api/routes.py").read_text(encoding="utf-8")
fx["routes"] = sorted(set(re.findall(
    r'@api_router\.(?:get|post|put|delete|patch)\("([^"]+)"', routes_txt)))
_NOTE = (
    "; ASAP-VISION-SYNC-01 wave2 (31.10.2026): Δ каталога +12 ParamSpec — "
    "PG-only ключи распознавания models.vision_max_output_tokens/"
    "vision_reasoning/vision_structured_output (группа models_vision) и "
    "limits.vision_* (ожидание готовности, окно связи, срок ожидающего "
    "запроса, lease/очередь/срок жизни/попытки/backoff watchdog). REGISTRY "
    "583→595, GROUPS 120 (0), _TAB_BY_GROUP 118 (0), TAB_RULES 22 in-place, "
    "delta 177→189; Settings без новых полей (env ClassVar-дефолты); secret — "
    "нет. routes.py не менялся — ROUTES_SHA256_F11 не переутверждается."
)
if "ASAP-VISION-SYNC-01 wave2" not in fx.get("superseded_by", ""):
    fx["superseded_by"] = fx.get("superseded_by", "") + _NOTE
_write_json_crlf(fx_path, fx)
print("f8_baseline updated:", fx["counts"], "routes:", len(fx["routes"]))

cb_path = ROOT / "tests/fixtures/round1025/catalog_baseline.json"
cb = json.loads(cb_path.read_text(encoding="utf-8"))
from services import param_catalog as pc  # noqa: E402

cb["registry_keys"] = sorted(pc.REGISTRY.keys())
cb["group_ids"] = sorted(g.id for g in pc.GROUPS)
cb["group_tab"] = {gid: pc.group_tab(gid)
                   for gid in sorted(g.id for g in pc.GROUPS)}
cb["tab_nav"] = {tid: pc.tab_nav(tid) for tid in sorted(cb["tab_nav"])}
cb["counts"] = {"REGISTRY": len(pc.REGISTRY), "GROUPS": len(pc.GROUPS),
                "_TAB_BY_GROUP": len(pc._TAB_BY_GROUP),
                "TAB_RULES": len(pc.TAB_RULES)}
_write_json_crlf(cb_path, cb)
print("catalog_baseline keys:", len(cb["registry_keys"]))

# Шаг 3) канон-пины каталога в тестах (583→595 / 177→189) ------------------
_REPLACEMENTS = (
    (r"len\(pc\.REGISTRY\) == 583", "len(pc.REGISTRY) == 595"),
    (r"len\(REGISTRY\) == 583", "len(REGISTRY) == 595"),
    (r'REGISTRY"\] == 583', 'REGISTRY"] == 595'),
    (r"len\(rows\) == 583", "len(rows) == 595"),
    (r'registry_keys"\]\) == 583', 'registry_keys"]) == 595'),
    (r"len\(keys\) == 583", "len(keys) == 595"),
    (r"len\(tsv\) - 1 == 583", "len(tsv) - 1 == 595"),
    (r'"583" in meta', '"595" in meta'),
    (r'"583" in res\.stdout', '"595" in res.stdout'),
    (r'FIXTURE\["counts"\]\["delta"\] == 177',
     'FIXTURE["counts"]["delta"] == 189'),
    (r'"177" in meta', '"189" in meta'),
    # категоризованный счётчик (env/PG-only записи с category): 558 → 570
    (r"== 558\b", "== 570"),
    # комментарии-провенанс (не код, но пин-текст читают люди)
    (r"reissue под 583/177", "reissue под 595/189"),
)
changed = 0
for path in sorted((ROOT / "tests").glob("*.py")):
    text = path.read_text(encoding="utf-8")
    new = text
    for pat, repl in _REPLACEMENTS:
        new = re.sub(pat, repl, new)
    if new != text:
        path.write_text(new, encoding="utf-8", newline="")
        changed += 1
print("test pins synced in %d files" % changed)

# Шаг 4) осознанное переутверждение hash каталога (L-F11S-1) ---------------
_PIN_PATH = ROOT / "tests/test_round1025_f8_registry.py"
_pin_text = _PIN_PATH.read_text(encoding="utf-8")
_new_hash = sha("services/param_catalog.py")
_pin_text = re.sub(
    r'(PARAM_CATALOG_SHA256_FOLLOWUP = \(\r?\n\s*")[0-9a-f]{64}(")',
    lambda m: m.group(1) + _new_hash + m.group(2), _pin_text)
_PIN_PATH.write_text(_pin_text, encoding="utf-8", newline="")
print("PARAM_CATALOG_SHA256_FOLLOWUP =", _new_hash)
