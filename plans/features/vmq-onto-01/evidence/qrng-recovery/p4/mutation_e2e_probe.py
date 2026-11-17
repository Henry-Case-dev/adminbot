# -*- coding: utf-8 -*-
"""QRNG P4 — e2e-mutations (harness/UI), каждая обязана уронить
`tools/ui_qrng_p4_e2e.py`.

Мutations:
  E1 — HTTP-сервер отдаёт CSS как application/octet-stream (CSS не применён);
  E2 — status stub снова «эхо primary»: IBM зелёный при configured=false;
  E3 — Sleep-карточка удалена с workspace-страницы;
  E4 — fallback-строка снова flex-wrap (стрелки отрываются на 390/320).

Файлы восстанавливаются в finally; sha256 до/после сверяется.
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
TOOL = ROOT / "tools" / "ui_qrng_p4_e2e.py"
INDEX = ROOT / "web" / "index.html"
PY = sys.executable

MUTATIONS = [
    {
        "id": "E1",
        "what": "CSS отдаётся как application/octet-stream (не применён)",
        "file": TOOL,
        "pairs": [(
            "        if ctype is None:\n"
            "            ctype = _MIME.get(os.path.splitext(rel)[1].lower(),\n"
            "                              \"application/octet-stream\")\n",
            "        ctype = \"application/octet-stream\"\n",
        )],
    },
    {
        "id": "E2",
        "what": "status stub: IBM зелёный при configured=false (эхо primary)",
        "file": TOOL,
        "pairs": [(
            "        for pid in order:\n"
            "            if configured.get(pid) or reserve.get(pid, 0) > 0:\n"
            "                effective = pid\n"
            "                break\n",
            "        effective = primary\n",
        )],
    },
    {
        "id": "E3",
        "what": "Sleep-карточка удалена с workspace-страницы",
        "file": INDEX,
        "pairs": [(
            "                        && workspaceModule.id === 'mod_sleep'\n"
            "                        && (workspaceTab === 'overview'",
            "                        && workspaceModule.id === 'mod_other'\n"
            "                        && (workspaceTab === 'overview'",
        )],
    },
    {
        "id": "E4",
        "what": "стрелки fallback уходят на отдельную строку (flex-wrap+width:100%)",
        "file": INDEX,
        "pairs": [
            ('class="flex items-center gap-2 rounded-lg bg-white/5 '
             'px-2 py-1 mb-1"',
             'class="flex items-center gap-2 flex-wrap rounded-lg bg-white/5 '
             'px-2 py-1 mb-1"'),
            ('<div class="flex items-center gap-1 shrink-0">',
             '<div class="flex items-center gap-1 shrink-0" '
             'style="width:100%">'),
        ],
    },
]


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


rows = []
for mut in MUTATIONS:
    path = mut["file"]
    original = path.read_bytes()
    before = sha(path)
    # F2 review: checkout с core.autocrlf=true не должен ломать multi-line
    # anchors — сравниваем в LF, записываем в исходных окончаниях строк.
    had_crlf = b"\r\n" in original
    text = original.decode("utf-8").replace("\r\n", "\n")
    ok_anchor = True
    for anchor, repl in mut["pairs"]:
        if anchor not in text:
            ok_anchor = False
            break
        text = text.replace(anchor, repl, 1)
    row = {"id": mut["id"], "what": mut["what"],
           "file": str(path.relative_to(ROOT))}
    if not ok_anchor:
        row.update({"killed": False, "error": "anchor not found"})
        rows.append(row)
        continue
    try:
        out_text = text.replace("\n", "\r\n") if had_crlf else text
        path.write_bytes(out_text.encode("utf-8"))
        res = subprocess.run(
            [PY, str(TOOL)], cwd=str(ROOT), capture_output=True, text=True,
            timeout=180)
        out = (res.stdout or "") + (res.stderr or "")
        row["exit"] = res.returncode
        row["killed"] = res.returncode != 0
        row["first_failure"] = next(
            (ln.strip() for ln in out.splitlines()
             if ln.strip().startswith('"ok": false')
             or "TimeoutError" in ln or "AssertionError" in ln), "")
    finally:
        path.write_bytes(original)
        row["restored_sha_ok"] = sha(path) == before
    rows.append(row)

report = {
    "test": "tools/ui_qrng_p4_e2e.py",
    "mutations": rows,
    "killed": sum(1 for r in rows if r.get("killed")),
    "total": len(rows),
    "all_restored": all(r.get("restored_sha_ok") for r in rows
                        if "restored_sha_ok" in r),
    "ok": all(r.get("killed") and r.get("restored_sha_ok") for r in rows),
}
payload = json.dumps(report, ensure_ascii=False, indent=2)
out_path = os.environ.get("QRNG_P4_MUTE_OUT")
if out_path:
    Path(out_path).write_text(payload + "\n", encoding="utf-8")
print(payload)
sys.exit(0 if report["ok"] else 1)
