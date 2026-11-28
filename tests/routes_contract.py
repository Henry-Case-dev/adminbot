"""Контракт маршрутов `web/api/routes.py` (замена byte-freeze sha256).

Смысл: при любом изменении поведения маршрутов (удаление/переименование,
смена HTTP-метода, снятие RBAC/проверки прав, дубль маршрута, появление
необъявленного маршрута) контракт обязан упасть. Комментарии,
переформатирование и правка тела без изменения маршрута и проверок доступа
контракт НЕ ломают — именно это устраняет механический re-pin полного
sha256 файла.

Манифест (``tests/fixtures/routes_contract.json``, schema 2) — объявленный
контракт:
  * ``path`` + ``methods`` — фактический набор маршрутов routes.py;
  * ``init_data`` — маршрут требует Telegram initData (``get_tma_user``);
  * ``direct_checks`` — проверки доступа в самом обработчике (тело +
    сигнатура: RBAC-зависимости и явные guard-вызовы, для
    ``requires_permission``/``requires_recovery``/``match_permission`` —
    вместе с запрошенным правом);
  * ``helper_checks`` — проверки, достижимые через module-level хелперы
    (до двух уровней вызовов от обработчика).

``direct_checks`` и ``helper_checks`` сравниваются **независимо**: удаление
прямого guard'а всегда меняет ``direct_checks``, даже если одноимённый guard
остался в хелпере (F-BAR-08). Наборы могут пересекаться по имени.

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
MANIFEST_SCHEMA = 2
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
    "can_access_chat",
    "gate_authorization",
    "get_tma_user",
    "guard_admin_lockout",
    "guard_last_wildcard",
    "match_permission",
    "requires_global_admin",
    "requires_permission",
    "requires_recovery",
    "user_is_global_admin",
    "validate_permissions",
})
# Прежнее имя набора сохранено как совместимый алиас.
GUARD_CALLS = EXPLICIT_GUARD_CALLS

# Эвристика имени inline-проверки доступа (контекст ВЫЗОВА). Проверка,
# названная по этим соглашениям, попадает в ``checks`` без ручного добавления
# в whitelist — следующая inline-проверка не выпадет из контракта.
_GUARD_NAME_RE = re.compile(
    r"(?:^|_)requires?_"      # requires_permission, _prompt_require_edit
    r"|^_?assert"             # _assert_*, assert_*
    r"|_guard$"               # _random_selector_guard, _meme_template_guard
    r"|_rights$"              # _recheck_config_chat_rights, _recheck_meme_rights
    r"|^can_"                 # can_access_chat, can_edit_param, can_view_key_value
    r"|^guard_"               # guard_admin_lockout, guard_last_wildcard
)
# Подмножество для guard'ов, переданных ПО ССЫЛКЕ (callback/recheck=...):
# здесь широкие call-only шаблоны (``^can_``/``_access$``) не применяются,
# иначе локальные переменные и модули (``can_write``, ``prompt_access``,
# ``global_access``) попали бы в checks.
_GUARD_CALLBACK_RE = re.compile(
    r"(?:^|_)requires?_"
    r"|^_?assert"
    r"|_guard$"
    r"|_rights$"
)


def is_guard_call_name(name: str) -> bool:
    """Имя ВЫЗОВА похоже на проверку доступа (whitelist + эвристика)."""
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


def _is_guard_callback_name(name: str) -> bool:
    """Имя guard'а, переданного по ссылке (а не имени локальной переменной)."""
    if not name:
        return False
    if name in EXPLICIT_GUARD_CALLS:
        return True
    if _GUARD_CALLBACK_RE.search(name):
        return True
    if name.endswith("_admin") and (
        name.startswith(("_", "is_", "user_is_"))
        or name.endswith(("_global_admin", "_hidden_admin"))
    ):
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


def _own_nodes(fn: ast.AST):
    """Узлы тела обработчика БЕЗ вложенных функций (они — helper-уровень)."""
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
            continue
        yield node
        stack.extend(ast.iter_child_nodes(node))


def _nested_functions(fn: ast.AST) -> list[ast.AST]:
    """Непосредственно вложенные def'ы внутри обработчика/хелпера."""
    out: list[ast.AST] = []
    stack = list(ast.iter_child_nodes(fn))
    while stack:
        node = stack.pop()
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            out.append(node)
            continue
        if isinstance(node, ast.Lambda):
            continue
        stack.extend(ast.iter_child_nodes(node))
    return out


_PERMISSION_ARG_CALLS = frozenset({
    "requires_permission",
    "requires_recovery",
    "match_permission",   # alias requires_permission (F-BAR-09)
})


def _source_checks(fn: ast.AST) -> list[str]:
    """Прямые проверки доступа в теле обработчика и его сигнатуре.

    Без раскрытия вложенных функций и module-level хелперов: helper-уровень
    считается отдельно (``_helper_checks``) и сравнивается независимо —
    иначе одноимённый guard в хелпере маскирует удаление прямого (F-BAR-08).
    """
    checks: set[str] = set()
    called: set[str] = set()
    nodes = list(_own_nodes(fn))
    for node in nodes:
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name is None:
            continue
        called.add(name)
        if is_guard_call_name(name):
            if name in _PERMISSION_ARG_CALLS:
                args = _call_const_args(node)
                if args:
                    checks.add("%s:%s" % (name, args[0]))
                    continue
            checks.add(name)
    # Guard, переданный по ссылке (callback): ``recheck=_recheck_meme_rights``.
    for node in nodes:
        if (isinstance(node, ast.Name)
                and isinstance(node.ctx, ast.Load)
                and node.id not in called
                and _is_guard_callback_name(node.id)):
            checks.add(node.id)
    return sorted(checks)


def _called_helpers(fn: ast.AST, module_funcs: dict[str, ast.AST]) -> list[str]:
    """Module-level хелперы, вызываемые из обработчика (own body)."""
    called: set[str] = set()
    helpers: set[str] = set()
    for node in _own_nodes(fn):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if name is None:
            continue
        called.add(name)
        if (name in module_funcs and not is_guard_call_name(name)
                and module_funcs[name] is not fn):
            helpers.add(name)
    # Хелпер, переданный по ссылке (``recheck=_recheck_meme_rights``), —
    # это guard-callback, он уже учтён как прямой guard; сюда не идёт.
    return sorted(helpers)


def _helper_checks(fn: ast.AST, module_funcs: dict[str, ast.AST],
                   max_depth: int = 2) -> list[str]:
    """Проверки доступа, достижимые через helper-уровень.

    Helper-уровень: вложенные функции самого обработчика + module-level
    хелперы, вызываемые из обработчика, до 2 уровней. Может пересекаться с
    ``_source_checks(fn)`` по имени: наборы сравниваются независимо, поэтому
    удаление прямого guard'а всегда меняет ``direct_checks`` даже при наличии
    того же имени в хелпере (F-BAR-08). Глубина 2 нужна для цепочек вида
    ``_persona_can_edit`` → ``_persona_has_edit_action`` (F-BAR-09).
    """
    checks: set[str] = set()
    visited: set[str] = set()
    frontier: list[tuple[ast.AST, int]] = [(fn, 0)]
    while frontier:
        current, level = frontier.pop()
        for nested in _nested_functions(current):
            checks.update(_source_checks(nested))
            if level + 1 < max_depth:
                frontier.append((nested, level + 1))
        for helper in _called_helpers(current, module_funcs):
            if helper in visited:
                continue
            visited.add(helper)
            target = module_funcs.get(helper)
            if target is None:
                continue
            checks.update(_source_checks(target))
            if level + 1 < max_depth:
                frontier.append((target, level + 1))
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
        direct = set(_source_checks(fn))
        direct.update(name for name in deps if is_guard_call_name(name))
        helper = set(_helper_checks(fn, module_funcs))
        manifest.append({
            "path": route.path,
            "methods": methods,
            "init_data": "get_tma_user" in deps,
            "direct_checks": sorted(direct),
            "helper_checks": sorted(helper),
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


def route_checks(row: dict) -> list[str]:
    """Объединение прямых и helper-проверок строки манифеста (чтение/UI)."""
    return sorted(set(row.get("direct_checks", []))
                  | set(row.get("helper_checks", [])))


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
        assert exp["direct_checks"] == act["direct_checks"], (
            "изменены прямые проверки прав %s %s: %r -> %r"
            % (key[0], key[1], exp["direct_checks"], act["direct_checks"]))
        assert exp["helper_checks"] == act["helper_checks"], (
            "изменены проверки прав в хелперах %s %s: %r -> %r"
            % (key[0], key[1], exp["helper_checks"], act["helper_checks"]))
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
