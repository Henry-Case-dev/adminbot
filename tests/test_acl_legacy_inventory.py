"""MOD-ACL-UX-01 M4C C3 / MAC-S8-LEG-01 — read-only legacy inventory.

Проверяется:
  * `tools/acl_legacy_inventory.py` строит JSON по реальным
    @api_router/@access_router и guard'ам (не по руками переписанному списку);
  * новые C3-маршруты видны с правильным guard/resource;
  * diff с каталогом не находит guard'ов без каталога (guarded_without=0);
  * legacy не удаляется: инвентарь только читает файлы;
  * runtime не импортирует tools/* (существующий F8-инвариант).
"""
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import acl_legacy_inventory as inv  # noqa: E402


def test_inventory_shape_and_c3_routes():
    report = inv.diff_against_catalog(inv.inventory(ROOT), ROOT)
    assert report["generated_from_sha"]
    assert report["routes"], "маршруты найдены"
    by_key = {(r["method"], r["path"]): r for r in report["routes"]}
    audit = by_key[("GET", "/api/access/audit")]
    assert audit["resource"] == "global"
    assert "inline_is_global_admin" in audit["guard"]
    reset = by_key[("DELETE",
                    "/api/access/chats/{chat_id}/param_permissions/{key}")]
    assert reset["resource"] == "global"
    roles = by_key[("GET", "/api/roles")]
    assert roles["resource"] == "section.access"
    assert roles["section"] == "access"
    role_put = by_key[("POST", "/api/roles")]
    assert role_put["resource"] == "global"
    assert report["guarded_without_catalog"] == []
    assert "catalog_without_guard" in report
    assert "unmatched" in report
    # Инвентарь не содержит значений/секретов.
    blob = json.dumps(report, ensure_ascii=False)
    assert "SENTINEL" not in blob and "api_key" not in blob.lower()


def test_check_subprocess_exit_zero():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "tools" / "acl_legacy_inventory.py"),
         "--check"],
        cwd=str(ROOT), capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    data = json.loads(proc.stdout)
    assert data["generated_from_sha"]
    assert data["guarded_without_catalog"] == []


def test_inventory_is_read_only_source():
    source = (ROOT / "tools" / "acl_legacy_inventory.py").read_text(
        encoding="utf-8")
    for token in ("INSERT INTO", "UPDATE ", "DELETE FROM", "CREATE TABLE",
                  "DROP "):
        assert token not in source, token
    # Runtime не импортирует tools/* (тот же F8-контракт).
    for sub in ("services", "web", "handlers"):
        for path in (ROOT / sub).rglob("*.py"):
            text = path.read_text(encoding="utf-8", errors="ignore")
            assert "tools.acl_legacy_inventory" not in text
            assert "from tools import" not in text
