"""SOUL-1 r3: сводка видимости ключей prompts.* из _r3_result.json ->
_r3_visibility-table.json (таблица для отчёта).

Запуск: .venv\\Scripts\\python.exe <этот файл>
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
with open(os.path.join(HERE, "_r3_result.json"), encoding="utf-8") as fh:
    res = json.load(fh)

rows = []
vps = ["320", "390", "430", "1024"]
base = res["viewports"]["320"]
keys = sorted(base.get("promptKeys") or [])
for k in keys:
    rows.append({
        "key": k,
        "in_catalog_and_api": True,
        "where_320": base["classify"].get(k),
        "where_390": res["viewports"]["390"]["classify"].get(k),
        "where_430": res["viewports"]["430"]["classify"].get(k),
        "where_1024": res["viewports"]["1024"]["classify"].get(k),
        "canEdit_admin": base["canEdit"].get(k),
        "persist_proven": (
            "real_typed_save" if k == "prompts.direct_l1_planner_system_prompt"
            else "real_select_save" if k == "prompts.verbilizer_default_mode"
            else "real_typed_save" if k == "prompts.verbilizer_mode_casual"
            else "same_path_not_exercised"),
    })

summary = {
    "total_prompts_keys_in_api": len(keys),
    "hidden_in_catalog_excluded": ["prompts.summary_cover_style_id"],
    "hidden_reason": "catalog hidden=True -> /api/config исключает (как и до правки)",
    "where_counts_320": {},
    "persist_proof": {
        "l1": "все 4 вьюпорта: ввод -> sticky Save -> POST -> reload",
        "mode_casual": "все 4 вьюпорта: ввод -> sticky Save -> POST -> reload",
        "default_mode": "все 4 вьюпорта: смена select -> автосейв POST -> reload",
    },
    "groups": {
        "rendered_as_cards": 8,
        "prompts_verbilizer": ("карточка группы не рендерится намеренно под V2 "
                               "(index.html:2305-2308); 4 ключа группы "
                               "достижимы/редактируемы: 3 mode_tabs в карточках "
                               "модулей + fallback-select в шапке"),
        "limits_anticliche": ("generic-карточка не рендерится намеренно "
                              "(F7/ADR-1024-3: ключ редактируется в карточке "
                              "монитора анти-клише)"),
    },
}
for r in rows:
    w = r["where_320"]
    summary["where_counts_320"][w] = \
        summary["where_counts_320"].get(w, 0) + 1

with open(os.path.join(HERE, "_r3_visibility-table.json"), "w",
          encoding="utf-8") as fh:
    json.dump({"summary": summary, "rows": rows}, fh,
              ensure_ascii=False, indent=1)

for r in rows:
    print("%-55s %-14s edit=%s persist=%s" % (
        r["key"], r["where_320"], r["canEdit_admin"], r["persist_proven"]))
print(json.dumps(summary, ensure_ascii=False, indent=1))
