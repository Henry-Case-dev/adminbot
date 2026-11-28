"""Контракт маршрутов `web/api/routes.py` (замена byte-freeze sha256).

Смысл: при любом изменении поведения маршрутов (удаление/переименование,
смена HTTP-метода, снятие RBAC/проверки прав, появление необъявленного
маршрута) контракт обязан упасть. Комментарии/переформатирование/правка
тела без изменения маршрута и проверок доступа контракт НЕ ломают —
именно это устраняет механический re-pin полного sha256 файла.

Манифест (``tests/fixtures/routes_contract.json``) — объявленный контракт:
  * ``path`` + ``methods`` — фактический набор маршрутов routes.py;
  * ``init_data`` — маршрут требует Telegram initData (``get_tma_user``);
  * ``checks`` — нормализованный набор проверок доступа внутри обработчика
    (RBAC-зависимости и явные guard-вызовы, для ``requires_permission`` —
    вместе с запрошенным правом).

Изменение манифеста — осознанное объявление нового контракта, а не
следствие любой правки файла.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTES_PATH = ROOT / "web" / "api" / "routes.py"
MANIFEST_PATH = ROOT / "tests" / "fixtures" / "routes_contract.json"

# Guard-вызовы, которые обязаны сохраняться у защищённых маршрутов.
GUARD_CALLS = frozenset({
    "_ctx_global_admin",
    "_is_global_admin",
    "_prompt_require_edit",
    "_prompt_require_view",
    "_prompt_require_revision_view",
    "_require_chat_access",
    "_ensure_keyvalue_object",
    "user_is_global_admin",
    "requires_global_admin",
    "requires_permission",
    "requires_recovery",
    "get_tma_user",
})


def _call_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _call_const_args(node: ast.Call) -> list[str]:
    out: list[str] = []
    for arg in node.args:
        if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
            out.append(arg.value)
    for kw in node.keywords:
        if isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
            out.append(kw.value.value)
    return out


def _source_checks(fn: ast.AST) -> list[str]:
    checks: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name not in GUARD_CALLS:
            continue
        if name in ("requires_permission", "requires_recovery"):
            args = _call_const_args(node)
            if args:
                checks.add("%s:%s" % (name, args[0]))
                continue
        checks.add(name)
    return sorted(checks)


def _route_decorators(fn: ast.AST) -> list[tuple[str, str]]:
    found: list[tuple[str, str]] = []
    for dec in getattr(fn, "decorator_list", []):
        if not isinstance(dec, ast.Call):
            continue
        func = dec.func
        if not (isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "api_router"):
            continue
        if not dec.args or not isinstance(dec.args[0], ast.Constant):
            continue
        path = dec.args[0].value
        if not isinstance(path, str):
            continue
        found.append((func.attr.upper(), path))
    return found


def _dependency_names(dep) -> set[str]:
    names: set[str] = set()
    call = getattr(dep, "call", None)
    if call is not None:
        names.add(getattr(call, "__name__", str(call)))
    for child in getattr(dep, "dependencies", []) or []:
        names |= _dependency_names(child)
    return names


def collect_routes() -> list[dict]:
    """Собрать фактический контракт routes.py (детерминированно)."""
    from fastapi.routing import APIRoute

    from web.api import routes as routes_mod

    source = ROUTES_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    by_path: dict[tuple[str, str], ast.AST] = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for method, path in _route_decorators(node):
            by_path[(method, path)] = node

    manifest: list[dict] = []
    for route in routes_mod.api_router.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = sorted(route.methods)
        deps = _dependency_names(route.dependant)
        fn = next((by_path.get((method, route.path)) for method in methods
                   if (method, route.path) in by_path), None)
        checks = _source_checks(fn) if fn is not None else []
        checks = sorted(set(checks) | (deps & GUARD_CALLS))
        manifest.append({
            "path": route.path,
            "methods": methods,
            "init_data": "get_tma_user" in deps,
            "checks": checks,
        })
    manifest.sort(key=lambda item: (item["path"], item["methods"]))
    return manifest


def load_manifest() -> dict:
    return json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))


def public_routes(manifest: list[dict] | None = None) -> set[str]:
    rows = manifest if manifest is not None else load_manifest()["routes"]
    return {row["path"] for row in rows if not row["init_data"]}


def assert_routes_contract_intact() -> None:
    """Главная проверка: живой routes.py соответствует объявленному контракту."""
    expected = load_manifest()["routes"]
    actual = collect_routes()
    exp_map = {(r["path"], tuple(r["methods"])): r for r in expected}
    act_map = {(r["path"], tuple(r["methods"])): r for r in actual}
    missing = sorted(set(exp_map) - set(act_map))
    unexpected = sorted(set(act_map) - set(exp_map))
    assert not missing, "маршруты контракта отсутствуют в routes.py: %r" % (
        missing,)
    assert not unexpected, "необъявленные маршруты в routes.py: %r" % (
        unexpected,)
    for key in sorted(exp_map):
        exp, act = exp_map[key], act_map[key]
        assert exp["init_data"] == act["init_data"], (
            "изменена auth-модель %s %s: init_data %r -> %r"
            % (key[0], key[1], exp["init_data"], act["init_data"]))
        assert exp["checks"] == act["checks"], (
            "изменены проверки прав %s %s: %r -> %r"
            % (key[0], key[1], exp["checks"], act["checks"]))
    # Инвариант: без initData — только явно публичные маршруты.
    non_public_without_auth = sorted(
        r["path"] for r in actual if not r["init_data"])
    assert set(non_public_without_auth) == public_routes(expected), (
        "публичный доступ без initData не совпадает с контрактом: %r"
        % (non_public_without_auth,))
