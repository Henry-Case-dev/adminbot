"""Контракт маршрутов `web/api/routes.py` (замена byte-freeze sha256).

Смысл: при любом изменении поведения маршрутов (удаление/переименование,
смена HTTP-метода, снятие RBAC/проверки прав, дубль маршрута, появление
необъявленного маршрута) контракт обязан упасть. Комментарии,
переформатирование и правка тела без изменения маршрута и проверок доступа
контракт НЕ ломают — именно это устраняет механический re-pin полного
sha256 файла.

Манифест (``tests/fixtures/routes_contract.json``) — объявленный контракт:
  * ``path`` + ``methods`` — фактический набор маршрутов routes.py;
  * ``init_data`` — маршрут требует Telegram initData (``get_tma_user``);
  * ``checks`` — нормализованный набор проверок доступа внутри обработчика
    (RBAC-зависимости и явные guard-вызовы, для ``requires_permission`` —
    вместе с запрошенным правом).

Изменение манифеста — осознанное объявление нового контракта, а не
следствие любой правки файла.

Переэмиссия манифеста::

    python -m tests.routes_contract --emit

Сверка без записи::

    python -m tests.routes_contract --check
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ROUTES_PATH = ROOT / "web" / "api" / "routes.py"
MANIFEST_PATH = ROOT / "tests" / "fixtures" / "routes_contract.json"
MANIFEST_SCHEMA = 1
MANIFEST_SOURCE = "web/api/routes.py"

# Явные guard-имена, которые не выводятся эвристикой ниже (или приходят как
# зависимости уровня маршрута: ``get_tma_user`` — из ``Depends``).
EXPLICIT_GUARD_CALLS = frozenset({
    "_ctx_global_admin",
    "_ensure_keyvalue_object",
    "_is_global_admin",
    "_prompt_require_edit",
    "_prompt_require_view",
    "_prompt_require_revision_view",
    "_require_chat_access",
    "get_tma_user",
    "requires_global_admin",
    "requires_permission",
    "requires_recovery",
    "user_is_global_admin",
})
# Прежнее имя набора сохранено как совместимый алиас.
GUARD_CALLS = EXPLICIT_GUARD_CALLS

# Эвристика имени inline-проверки доступа. Проверка, названная по этим
# соглашениям, попадает в ``checks`` без ручного добавления в whitelist —
# следующая inline-проверка не выпадет из контракта.
_GUARD_NAME_RE = re.compile(
    r"(?:^|_)requires?_"      # requires_permission, _prompt_require_edit
    r"|^_?assert"             # _assert_*, assert_*
    r"|_guard$"               # _random_selector_guard, _meme_template_guard
    r"|_rights$"              # _recheck_config_chat_rights, _recheck_meme_rights
)


def is_guard_call_name(name: str) -> bool:
    """Имя вызова/ссылки похоже на проверку доступа (whitelist + эвристика)."""
    if not name:
        return False
    if name in EXPLICIT_GUARD_CALLS:
        return True
    if _GUARD_NAME_RE.search(name):
        return True
    # *_admin хелперы доступа: private (``_..._admin``), ``is_/user_is_`` или
    # известный security-суффикс. Бизнес-операции add_/remove_/upsert_admin
    # сюда не попадают.
    if name.endswith("_admin"):
        if name.startswith(("_", "is_", "user_is_")):
            return True
        if name.endswith(("_global_admin", "_hidden_admin")):
            return True
    return False


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


def _source_checks(fn: ast.AST, module_funcs: dict[str, ast.AST] | None = None) -> list[str]:
    """Проверки доступа в теле обработчика и его сигнатуре.

    ``module_funcs`` (только для маршрутов): ровно на один уровень
    раскрываются вызовы module-level хелперов этого модуля — например,
    ``_post_config_global``. Так guard внутри общего хелпера не становится
    невидимым контракту. Глубже не идём: контракт остаётся маршрутным, а не
    графом всего модуля.
    """
    checks: set[str] = set()
    called: set[str] = set()
    helpers: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name is None:
            continue
        called.add(name)
        if is_guard_call_name(name):
            if name in ("requires_permission", "requires_recovery"):
                args = _call_const_args(node)
                if args:
                    checks.add("%s:%s" % (name, args[0]))
                    continue
            checks.add(name)
        elif module_funcs and name in module_funcs:
            helpers.add(name)
    # Guard, переданный по ссылке (callback): ``recheck=_recheck_meme_rights``.
    for node in ast.walk(fn):
        if (isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id not in called
                and is_guard_call_name(node.id)):
            checks.add(node.id)
    if module_funcs:
        for helper in sorted(helpers):
            target = module_funcs.get(helper)
            if target is None or target is fn or is_guard_call_name(helper):
                continue
            checks.update(_source_checks(target))
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


def ast_route_records(source: str) -> list[dict]:
    """AST-декораторы ``api_router``: method/path/handler/lineno."""
    tree = ast.parse(source)
    records: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for method, path in _route_decorators(node):
            records.append({
                "method": method,
                "path": path,
                "handler": node.name,
                "lineno": node.lineno,
            })
    return records


def _dependency_names(dep) -> set[str]:
    names: set[str] = set()
    call = getattr(dep, "call", None)
    if call is not None:
        names.add(getattr(call, "__name__", str(call)))
    for child in getattr(dep, "dependencies", []) or []:
        names |= _dependency_names(child)
    return names


def duplicate_route_keys(rows: list[dict]) -> list[tuple[str, tuple[str, ...]]]:
    """Ключи ``(path, methods)``, объявленные более одного раза."""
    counts = Counter((row["path"], tuple(row["methods"])) for row in rows)
    return sorted(key for key, count in counts.items() if count > 1)


def overlapping_route_methods(rows: list[dict]) -> list[tuple[str, str]]:
    """Пары ``(path, method)``, зарегистрированные в двух обработчиках."""
    counts: Counter = Counter()
    for row in rows:
        for method in row["methods"]:
            counts[(row["path"], method)] += 1
    return sorted(key for key, count in counts.items() if count > 1)


def assert_routes_unique(rows: list[dict], where: str) -> None:
    """Отказ при дубле маршрута: FastAPI диспатчит первый обработчик.

    Второй обработчик того же ``path``+method недостижим, но его наличие
    означает, что порядок регистрации определяет, какая проверка доступа
    реально применяется. Молча схлопывать такие записи нельзя.
    """
    duplicates = duplicate_route_keys(rows)
    assert not duplicates, (
        "неуникальные (path, methods) в %s: %r — второй обработчик с тем же "
        "путём/методом недостижим и может ослабить проверку доступа"
        % (where, duplicates))
    overlaps = overlapping_route_methods(rows)
    assert not overlaps, (
        "метод зарегистрирован дважды для одного path в %s: %r"
        % (where, overlaps))


def collect_routes() -> list[dict]:
    """Собрать фактический контракт routes.py (детерминированно)."""
    from fastapi.routing import APIRoute

    from web.api import routes as routes_mod

    source = ROUTES_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    module_funcs = {
        node.name: node for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    handler_nodes = {
        node.name: node for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    ast_records = ast_route_records(source)
    # Дубль на уровне декораторов: два обработчика (или два декоратора на
    # одном обработчике) с одинаковым (method, path).
    assert_routes_unique(
        [{"path": rec["path"], "methods": [rec["method"]]}
         for rec in ast_records],
        "AST-декораторы routes.py")
    by_path: dict[tuple[str, str], ast.AST] = {}
    for rec in ast_records:
        node = handler_nodes.get(rec["handler"])
        assert node is not None, (
            "AST-декоратор %s %s: обработчик %r не найден"
            % (rec["method"], rec["path"], rec["handler"]))
        by_path[(rec["method"], rec["path"])] = node

    manifest: list[dict] = []
    for route in routes_mod.api_router.routes:
        if not isinstance(route, APIRoute):
            continue
        methods = sorted(route.methods)
        deps = _dependency_names(route.dependant)
        fn = next((by_path.get((method, route.path)) for method in methods
                   if (method, route.path) in by_path), None)
        assert fn is not None, (
            "маршрут %s %r зарегистрирован без AST-декоратора api_router: "
            "проверки доступа нечем проверить" % (route.path, methods))
        checks = set(_source_checks(fn, module_funcs))
        checks.update(name for name in deps if is_guard_call_name(name))
        manifest.append({
            "path": route.path,
            "methods": methods,
            "init_data": "get_tma_user" in deps,
            "checks": sorted(checks),
        })
    # Дубль на уровне живого роутера (включая пересечение методов).
    assert_routes_unique(manifest, "зарегистрированные маршруты FastAPI")
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
    assert_routes_unique(expected, "манифест tests/fixtures/routes_contract.json")
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


def manifest_payload() -> dict:
    """Полный объявленный контракт для записи в манифест."""
    return {
        "schema": MANIFEST_SCHEMA,
        "source": MANIFEST_SOURCE,
        "routes": collect_routes(),
    }


def render_manifest() -> str:
    """Текст манифеста в каноническом формате (LF, indent=2, хвостовой \\n)."""
    return json.dumps(manifest_payload(), ensure_ascii=False, indent=2) + "\n"


def emit_manifest(path: Path | str | None = None) -> Path:
    """Переэмитировать манифест; цель по умолчанию — объявленный fixture."""
    target = Path(path) if path is not None else MANIFEST_PATH
    target.write_text(render_manifest(), encoding="utf-8", newline="\n")
    return target


def manifest_mismatch(path: Path | str | None = None) -> list[str]:
    """Расхождения файла манифеста с рендером из живого routes.py."""
    target = Path(path) if path is not None else MANIFEST_PATH
    expected = render_manifest()
    actual = target.read_text(encoding="utf-8")
    if expected == actual:
        return []
    expected_lines = expected.splitlines()
    actual_lines = actual.splitlines()
    diff = [
        "%d: ожидалось %r, в файле %r" % (index + 1, exp, act)
        for index, (exp, act) in enumerate(zip(expected_lines, actual_lines))
        if exp != act
    ]
    if len(expected_lines) != len(actual_lines):
        diff.append("строк: ожидалось %d, в файле %d"
                    % (len(expected_lines), len(actual_lines)))
    return diff or ["файл отличается от рендера (хвостовой перевод строки)"]


def check_manifest(path: Path | str | None = None) -> int:
    """Сверить манифест с routes.py. 0 — совпадает, 1 — расходится."""
    target = Path(path) if path is not None else MANIFEST_PATH
    mismatch = manifest_mismatch(target)
    if mismatch:
        print("CHECK FAILED: %s расходится с web/api/routes.py" % target)
        for line in mismatch[:20]:
            print("  " + line)
        print("Переэмиссия: python -m tests.routes_contract --emit")
        return 1
    print("CHECK OK: %s соответствует web/api/routes.py" % target)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tests.routes_contract",
        description="Манифест контракта маршрутов web/api/routes.py.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument(
        "--emit", action="store_true",
        help="переэмитировать tests/fixtures/routes_contract.json")
    group.add_argument(
        "--check", action="store_true",
        help="сверить манифест с routes.py, ничего не записывая")
    args = parser.parse_args(argv)
    if args.emit:
        target = emit_manifest()
        count = len(load_manifest()["routes"])
        print("OK: манифест записан: %s (%d маршрутов)" % (target, count))
        return 0
    return check_manifest()


if __name__ == "__main__":
    sys.exit(main())
