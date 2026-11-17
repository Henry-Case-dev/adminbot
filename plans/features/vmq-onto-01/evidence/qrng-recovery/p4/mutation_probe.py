# -*- coding: utf-8 -*-
"""QRNG P4 — mutation-проба UI-инвариантов (каждая мутация обязана РАСКРАСИТЬ
`tests/js/qrng_p4_random_ui_test.js`).

Работает на копиях байтов: перед мутацией файл читается, после прогона
восстанавливается в `finally`; sha256 до/после сверяется. Никаких git-команд,
меняющих дерево, не используется.

Запуск: .venv\\Scripts\\python.exe
        plans/features/vmq-onto-01/evidence/qrng-recovery/p4/mutation_probe.py
"""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[6]
APP = ROOT / "web" / "app.js"
INDEX = ROOT / "web" / "index.html"
TEST = ROOT / "tests" / "js" / "qrng_p4_random_ui_test.js"
NODE = os.environ.get("NODE_BIN", "node")

MUTATIONS = [
    {
        "id": "M1",
        "what": "dummy-селектор: значение не уходит в POST /api/config",
        "file": APP,
        "pairs": [(
            "        var res = await this.qrngPersist(items);",
            "        var res = { saved: [item.key] };\n"
            "        void this.qrngPersist;",
        )],
    },
    {
        "id": "M2",
        "what": "Lizaonair возвращён в UI-бандл",
        "file": INDEX,
        "pairs": [(
            '<div class="card p-4 col-span-full" data-random-sources>',
            '<div class="text-xs" data-mut="excluded">Lizaonair</div>\n'
            '                <div class="card p-4 col-span-full" '
            'data-random-sources>',
        )],
    },
    {
        "id": "M3",
        "what": "подсказка снова обещает зачисление draft-партии",
        "file": APP,
        "pairs": [(
            "'значения не зачисляются в рабочий запас. Сохранённый ключ при '",
            "'значения зачисляются в рабочий запас. Сохранённый ключ при '",
        )],
    },
    {
        "id": "M4",
        "what": "keys_random оставлен на вкладке LLM-провайдеров",
        "file": APP,
        "pairs": [(
            "            'keys_media'] },",
            "            'keys_media', 'keys_random'] },",
        )],
    },
    {
        "id": "M5",
        "what": "4-я опция селектора (дубль ANU) — UI расширяет контракт",
        "file": APP,
        "pairs": [(
            "  var QRNG_PROVIDERS = ['ibm_quantum', 'anu', 'lfdr'];",
            "  var QRNG_PROVIDERS = ['ibm_quantum', 'anu', 'lfdr', 'anu'];",
        )],
    },
    {
        "id": "M6",
        "what": "«Время ответа и защита» снова первая группа моделей",
        "file": APP,
        "pairs": [
            ("    { id: 'prov_policy', title: 'Время ответа и защита', "
             "blocks: ['llm_guard'] },\n", ""),
            ("  var PROVIDER_GROUPS = [\n",
             "  var PROVIDER_GROUPS = [\n"
             "    { id: 'prov_policy', title: 'Время ответа и защита', "
             "blocks: ['llm_guard'] },\n"),
        ],
    },
    {
        "id": "M7",
        "what": "fake green: PRNG-режим помечен badge-ok",
        "file": APP,
        "pairs": [(
            "        } else if (v.prngActive) {\n"
            "          stateCls = 'badge-warn';",
            "        } else if (v.prngActive) {\n"
            "          stateCls = 'badge-ok';",
        )],
    },
    {
        "id": "M8",
        "what": "старая подсказка про зачисление возвращена рядом",
        "file": INDEX,
        "pairs": [(
            "                          {{ randomDraftHint() }}",
            "                          Проверка использует ключ и зачисляет "
            "полученную партию в запас. {{ randomDraftHint() }}",
        )],
    },
    {
        "id": "M9",
        "what": "fallback_order оставляет primary (серверный guard 422)",
        "file": APP,
        "pairs": [(
            "          return QRNG_PROVIDERS.indexOf(id) >= 0 && id !== primary;",
            "          return QRNG_PROVIDERS.indexOf(id) >= 0;",
        )],
    },
    {
        "id": "M10",
        "what": "4-я карточка провайдера (дубль ANU)",
        "file": INDEX,
        "pairs": [(
            '<article class="card p-3" data-random-provider="lfdr">',
            '<article class="card p-3" data-random-provider="anu"></article>\n'
            '                    <article class="card p-3" '
            'data-random-provider="lfdr">',
        )],
    },
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_test() -> tuple[int, str]:
    res = subprocess.run([NODE, str(TEST)], cwd=str(ROOT),
                         capture_output=True, text=True, timeout=120)
    out = (res.stdout or "") + (res.stderr or "")
    return res.returncode, out


rows = []
for mut in MUTATIONS:
    path = mut["file"]
    original = path.read_bytes()
    before = sha(path)
    text = original.decode("utf-8")
    applied = True
    for anchor, replacement in mut["pairs"]:
        if anchor not in text:
            applied = False
            break
        text = text.replace(anchor, replacement, 1)
    row = {"id": mut["id"], "what": mut["what"], "file": str(path.relative_to(ROOT))}
    if not applied:
        row.update({"killed": False, "error": "anchor not found"})
        rows.append(row)
        continue
    try:
        path.write_text(text, encoding="utf-8", newline="")
        code, out = run_test()
        row["exit"] = code
        row["killed"] = (code != 0) and ("QRNG-P4-UI-OK" not in out)
        row["first_assertion"] = next(
            (ln.strip() for ln in out.splitlines()
             if ln.strip().startswith("AssertionError")), "")
    finally:
        path.write_bytes(original)
        row["restored_sha_ok"] = sha(path) == before
    rows.append(row)

report = {
    "test": "tests/js/qrng_p4_random_ui_test.js",
    "mutations": rows,
    "killed": sum(1 for r in rows if r.get("killed")),
    "total": len(rows),
    "all_restored": all(r.get("restored_sha_ok") for r in rows
                        if "restored_sha_ok" in r),
    "ok": all(r.get("killed") and r.get("restored_sha_ok") for r in rows),
}
payload = json.dumps(report, ensure_ascii=False, indent=2)
out_path = os.environ.get("QRNG_P4_MUT_OUT")
if out_path:
    Path(out_path).write_text(payload + "\n", encoding="utf-8")
print(payload)
sys.exit(0 if report["ok"] else 1)
