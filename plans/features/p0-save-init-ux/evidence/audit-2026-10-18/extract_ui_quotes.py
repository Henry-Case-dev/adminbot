"""Снимает ТОЧНЫЕ цитаты UI из prod-копии app.js (sha256 2757a25d…) в evidence.

Запуск: .venv\\Scripts\\python.exe .../extract_ui_quotes.py
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re

def _find_root(start: str) -> str:
    cur = os.path.abspath(start)
    while cur and cur != os.path.dirname(cur):
        if os.path.isfile(os.path.join(cur, "config", "settings.py")):
            return cur
        cur = os.path.dirname(cur)
    raise RuntimeError("repo root not found")


HERE = os.path.dirname(__file__)
_ROOT = _find_root(HERE)
PROD_APP = os.path.join(_ROOT, "OPENCODE_WORKFLOW_SCRATCH", "prod_app.js")
PROD_INDEX = os.path.join(_ROOT, "web", "index.html")

src = io.open(PROD_APP, encoding="utf-8", errors="replace").read()
lines = src.splitlines()
sha = hashlib.sha256(src.encode("utf-8")).hexdigest()

TARGETS = {
    "scope_autoswitch": r"speechScopeChoice = 'chat'",
    "save_style_catch_409": r"Документ не прошёл проверку или конфликт версии",
    "save_expression_catch": r"saveSpeechExpression: async function",
    "err_text": r"loreErrText: function",
    "api_error_message": r"throw new ApiError\(resp\.status, detail\)",
    "core_meta_toggle": r"saveSpeechCoreEnabled: async function",
    "reset_style_chat": r"resetStyleChat: async function",
    "x_chat_id_header": r"init\.headers\['X-Chat-Id'\] = String\(this\.activeChatId\)",
    "active_chat_restore": r"localStorage\.getItem\('adminbot\.active_chat_id'\)",
}

out: dict = {"prod_app_sha256": sha, "prod_app_len": len(src), "quotes": {}}
for name, pattern in TARGETS.items():
    rx = re.compile(pattern)
    for idx, line in enumerate(lines):
        if rx.search(line):
            lo = max(0, idx - 3)
            hi = min(len(lines), idx + 22)
            out["quotes"][name] = {
                "line": idx + 1,
                "snippet": "\n".join(f"{i + 1}: {lines[i]}" for i in range(lo, hi)),
            }
            break

index_html = io.open(PROD_INDEX, encoding="utf-8", errors="replace").read()
ih_lines = index_html.splitlines()
for idx, line in enumerate(ih_lines):
    if "saveSpeechExpression()" in line:
        out["quotes"]["scope_select_expression"] = {
            "line": idx + 1,
            "snippet": "\n".join(f"{i + 1}: {ih_lines[i]}"
                                 for i in range(max(0, idx - 6), min(len(ih_lines), idx + 8))),
        }
        break

with open(os.path.join(HERE, "ui_quotes_prod.json"), "w", encoding="utf-8") as fh:
    json.dump(out, fh, ensure_ascii=False, indent=2)
print(json.dumps(out, ensure_ascii=False, indent=2)[:5000])
