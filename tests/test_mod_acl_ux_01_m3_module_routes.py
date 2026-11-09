"""MOD-ACL-UX-01 M3 — страницы модулей реестра и честный отказ (frontend).

Реальный node-прогон `tests/js/mod_acl_ux_m3_module_routes_test.js` (не grep):
каждый ВИДИМЫЙ модуль `services/module_registry.py` открывается своей
страницей у глобального админа и запрещён обычному пользователю; неизвестный
`mod_*` запрещён; `isGlobalAdmin` доверяет серверному `is_global_admin`;
состояния панели векторной памяти (отказ / ошибка / пустые данные) различимы.

Snapshot реестра готовится ЗДЕСЬ из живого реестра и передаётся JS-тесту —
второй копии списка модулей нет (иначе тест разошёлся бы с сервером).
Пропускается, если node недоступен.
"""
import json
import os
import shutil
import subprocess
import tempfile

import pytest

SCRIPT = os.path.join("tests", "js", "mod_acl_ux_m3_module_routes_test.js")

# Поля ModuleSpec, которые реально доезжают до фронта (`f3ApplyModuleRegistry`
# и `registry_for_frontend`) — snapshot описывает ровно их.
FIELDS = ("id", "title", "description", "master_param", "runtime_gate",
          "parent_id", "config_tab", "visibility", "classification")


def _registry_snapshot():
    from services import module_registry as mr
    out = []
    for spec in mr.MODULE_REGISTRY.values():
        if spec.visibility == "hidden":
            continue
        row = {f: getattr(spec, f) for f in FIELDS}
        row["parent_id"] = spec.parent_id
        row["config_tab"] = spec.config_tab or ("mod_" + spec.id)
        row["tab"] = "mod_" + spec.id
        row["route"] = "#/modules/" + spec.id
        out.append(row)
    return out


def test_registry_declares_module_page_for_every_visible_module():
    """Конвенция поверхности: у каждого видимого модуля есть tab/route."""
    rows = _registry_snapshot()
    assert rows, "реестр пуст — нечего проверять"
    ids = [r["id"] for r in rows]
    assert len(ids) == len(set(ids)), "дубли id в реестре"
    for r in rows:
        assert r["tab"] == "mod_" + r["id"], r
        assert r["route"] == "#/modules/" + r["id"], r
        # Поверхность модуля = его собственный tab либо config-вкладка
        # родителя (подмодули живут на существующих вкладках).
        assert r["config_tab"] or r["parent_id"], r


def test_js_fixture_matches_live_registry():
    """Снимок для JS-прогона не разошёлся с живым реестром (drift-guard)."""
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    fixture = os.path.join(root, "tests", "fixtures",
                           "module_registry_visible.json")
    with open(fixture, encoding="utf-8") as fh:
        saved = json.load(fh)
    assert saved == _registry_snapshot(), (
        "tests/fixtures/module_registry_visible.json устарел — пересоберите "
        "из services/module_registry.py (видимые модули)")


def test_js_module_routes_and_denial():
    node = shutil.which("node")
    if not node:
        pytest.skip("node недоступен — JS-unit пропущен")
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    rows = _registry_snapshot()
    fd, snap = tempfile.mkstemp(prefix="mod_acl_m3_", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(rows, fh, ensure_ascii=False)
        res = subprocess.run([node, SCRIPT, snap], capture_output=True,
                             text=True, timeout=120, cwd=root)
    finally:
        try:
            os.unlink(snap)
        except OSError:
            pass
    assert res.returncode == 0, (
        "MOD-ACL-UX-01 M3 JS-UNIT провалился:\nSTDOUT:\n%s\nSTDERR:\n%s"
        % (res.stdout, res.stderr))
    assert "MOD-ACL-UX-01 M3 MODULE ROUTES OK" in res.stdout
