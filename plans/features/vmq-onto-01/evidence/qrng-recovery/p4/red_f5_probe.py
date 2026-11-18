# -*- coding: utf-8 -*-
"""QRNG P4 — F5 RED-пробы (coverage гарантия не автоматическая).

(a) новый ключ в каталоге без переэмиссии fixture → Python-пин краснеет;
(b) удалён `data-random-primary` из index.html → JS F5-тест краснеет;
(c) удалён `data-cfg-key="memory.random_source"` → JS F5-тест краснеет.

Каждый прогон восстанавливает байты; GREEN текущего состояния проверяется
до RED-проб. JSON — в stdout / QRNG_P4_F5_OUT.
"""
import hashlib
import json
import os
import subprocess
import sys
import types
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:  # noqa: BLE001
    pass

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT))

from services import param_catalog as pc  # noqa: E402
from tests import test_frontend_tab_mapping as mapping  # noqa: E402

INDEX = ROOT / "web" / "index.html"
NODE = os.environ.get("NODE_BIN", "node")
F5_TEST = ROOT / "tests" / "js" / "round1025_f5_workspace_route_test.js"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_node() -> tuple[int, str]:
    res = subprocess.run([NODE, str(F5_TEST)], cwd=str(ROOT),
                         capture_output=True, text=True, timeout=120)
    return res.returncode, (res.stdout or "") + (res.stderr or "")


def mutate_index(pairs):
    original = INDEX.read_bytes()
    had_crlf = b"\r\n" in original
    text = original.decode("utf-8").replace("\r\n", "\n")
    for anchor, repl in pairs:
        if anchor not in text:
            INDEX.write_bytes(original)
            return {"killed": False, "error": "anchor not found",
                    "restored_sha_ok": sha(INDEX) == hashlib.sha256(
                        original).hexdigest()}
    for anchor, repl in pairs:
        text = text.replace(anchor, repl, 1)
    try:
        out_text = text.replace("\n", "\r\n") if had_crlf else text
        INDEX.write_bytes(out_text.encode("utf-8"))
        code, out = run_node()
        return {"killed": code != 0, "exit": code,
                "first_assertion": next(
                    (ln.strip() for ln in out.splitlines()
                     if ln.strip().startswith("AssertionError")), "")}
    finally:
        INDEX.write_bytes(original)


def _run_python_pin():
    mapping.TestModuleTabs().test_qrng_page_keys_fixture_matches_catalog()


report = {"ok": True, "probes": []}

# GREEN базовой линии (до мутаций).
try:
    _run_python_pin()
    green_py = True
except Exception:  # noqa: BLE001
    green_py = False
green_code, green_out = run_node()
report["green"] = {"python_pin": green_py,
                   "js_f5": green_code == 0
                   and "MODULE-WORKSPACE-OK" in green_out}
report["ok"] = report["ok"] and all(report["green"].values())

# (a) новый ключ в каталоге без fixture.
key = "__qrng_p4_red_new_key__"
pc.REGISTRY[key] = types.SimpleNamespace(
    pg_key="random.__red_new_key__", group="memory_random", hidden=False)
try:
    _run_python_pin()
    killed = False
    err = ""
except AssertionError as exc:
    killed = True
    err = str(exc).splitlines()[0]
finally:
    pc.REGISTRY.pop(key, None)
report["probes"].append({
    "id": "a",
    "what": "новый ключ каталога без fixture",
    "killed": killed,
    "first_assertion": err,
})
report["ok"] = report["ok"] and killed

# (b) удалён реальный контрол селектора.
row = mutate_index([("data-random-primary", "data-random-primary-removed")])
report["probes"].append({
    "id": "b", "what": "удалён data-random-primary", **row})
report["ok"] = report["ok"] and row.get("killed", False)

# (c) удалён marker ключа memory.random_source.
row = mutate_index([('data-cfg-key="memory.random_source"',
                     'data-cfg-key-removed="memory.random_source"')])
report["probes"].append({
    "id": "c", "what": "удалён data-cfg-key=memory.random_source", **row})
report["ok"] = report["ok"] and row.get("killed", False)

payload = json.dumps(report, ensure_ascii=False, indent=2)
out_path = os.environ.get("QRNG_P4_F5_OUT")
if out_path:
    Path(out_path).write_text(payload + "\n", encoding="utf-8")
print(payload)
sys.exit(0 if report["ok"] else 1)
