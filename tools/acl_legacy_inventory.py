"""MOD-ACL-UX-01 M4C C3 — read-only инвентарь legacy ACL-поверхности.

Не меняет продукт, не пишет в БД и не импортируется runtime. Разбирает
`@api_router`/`@access_router`/`@chat_lore_router`/`@memory_router` и guard'ы
из `web/api/*.py`, сверяет ресурсы с каталогом
(`known_sections()/ACTION_IDS/known_param_keys()`).

Запуск:
    python tools/acl_legacy_inventory.py            # JSON в stdout
    python tools/acl_legacy_inventory.py --out x.json
    python tools/acl_legacy_inventory.py --check    # 0, если surface разобран

Legacy-маршруты НЕ удаляются и НЕ мигрируются: это инвентарь для S8-LEG-01.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ROUTERS = {"api_router", "access_router", "chat_lore_router", "memory_router"}
ROUTER_PREFIX = {
    "api_router": "/api",
    "access_router": "/api/access",
    "chat_lore_router": "/api",
    "memory_router": "/api",
}
GUARD_PATTERNS = (
    ("requires_global_admin", re.compile(r"requires_global_admin\(\s*\)")),
    ("require_global_admin", re.compile(r"_require_global_admin\(")),
    ("inline_is_global_admin", re.compile(r"is_global_admin")),
    ("can_edit_param", re.compile(r"can_edit_param\(")),
    ("can_view_key_value", re.compile(r"can_view_key_value\(")),
    ("is_dm_owner", re.compile(r"is_dm_owner")),
)
REQUIRES_PERMISSION_RE = re.compile(
    r"requires_permission\(\s*[\"']([^\"']+)[\"']")


def _generated_from_sha() -> str | None:
    try:
        proc = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(ROOT),
            capture_output=True, text=True, timeout=10)
    except Exception:
        return None
    sha = (proc.stdout or "").strip()
    return sha if proc.returncode == 0 and sha else None


def _guards(source: str) -> list[str]:
    return [name for name, pattern in GUARD_PATTERNS
            if pattern.search(source)]


def _route_resource(source: str, guards: list[str],
                    actions: set[str] | None = None
                    ) -> tuple[str, str | None]:
    match = REQUIRES_PERMISSION_RE.search(source)
    if match:
        perm = match.group(1)
        if perm.startswith("action."):
            return perm, None
        if actions and perm in actions:
            return "action." + perm, None
        return "section." + perm, perm
    if "can_edit_param" in guards:
        return "param", None
    if "can_view_key_value" in guards:
        return "key", None
    if "requires_global_admin" in guards or "require_global_admin" in guards \
            or "inline_is_global_admin" in guards:
        return "global", None
    if "is_dm_owner" in guards:
        return "dm", None
    return "authenticated", None


def inventory(root: Path | None = None) -> dict:
    root = root or ROOT
    try:
        sys.path.insert(0, str(root))
        from services.permissions import ACTION_IDS as actions
    finally:
        sys.path.pop(0)
    routes: list[dict] = []
    unmatched: list[dict] = []
    for path in sorted((root / "web" / "api").glob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text, filename=str(path))
        except (OSError, SyntaxError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
                continue
            for dec in node.decorator_list:
                if not isinstance(dec, ast.Call) or not isinstance(
                        dec.func, ast.Attribute):
                    continue
                owner = dec.func.value
                if not isinstance(owner, ast.Name) or owner.id not in ROUTERS:
                    continue
                if not dec.args or not isinstance(dec.args[0], ast.Constant):
                    continue
                route_path = dec.args[0].value
                if not isinstance(route_path, str):
                    continue
                segment = ast.get_source_segment(text, node) or ""
                guards = _guards(segment)
                resource, section = _route_resource(segment, guards, actions)
                row = {
                    "method": dec.func.attr.upper(),
                    "path": ROUTER_PREFIX[owner.id] + route_path,
                    "file": str(path.relative_to(root)).replace("\\", "/"),
                    "function": node.name,
                    "guard_kind": guards[0] if guards else "authenticated_only",
                    "guard": ", ".join(guards) or "get_tma_user",
                    "resource": resource,
                }
                if section:
                    row["section"] = section
                routes.append(row)
                if not guards:
                    unmatched.append({"method": row["method"],
                                      "path": row["path"],
                                      "file": row["file"],
                                      "reason": "no_acl_guard"})
    routes.sort(key=lambda r: (r["path"], r["method"], r["file"]))
    return {
        "generated_from_sha": _generated_from_sha(),
        "root": str(root),
        "routes": routes,
        "unmatched": unmatched,
    }


def diff_against_catalog(report: dict, root: Path | None = None) -> dict:
    root = root or ROOT
    sys.path.insert(0, str(root))
    try:
        from services.param_catalog import known_param_keys, known_sections
        from services.permissions import ACTION_IDS
    finally:
        sys.path.pop(0)

    sections = set(known_sections())
    params = set(known_param_keys())
    actions = set(ACTION_IDS)
    guarded_sections = {r.get("section") for r in report["routes"]
                        if r.get("section")}
    has_param_surface = any(r["resource"] == "param"
                            for r in report["routes"])
    has_key_surface = any(r["resource"] == "key"
                          for r in report["routes"])
    catalog_without_guard = []
    if not has_param_surface:
        catalog_without_guard.extend(
            {"kind": "section", "id": section}
            for section in sorted(sections - guarded_sections))
        catalog_without_guard.extend(
            {"kind": "param", "id": key} for key in sorted(params))
    if not has_key_surface:
        catalog_without_guard.extend(
            {"kind": "key", "id": key} for key in sorted(params)
            if key.startswith("keys."))
    action_surfaces = {r["resource"] for r in report["routes"]
                       if (r.get("resource") or "").startswith("action.")}
    catalog_without_guard.extend(
        {"kind": "action", "id": action} for action in sorted(actions)
        if "action." + action not in action_surfaces)
    guarded_without_catalog = []
    for row in report["routes"]:
        section = row.get("section")
        if section and section not in sections:
            guarded_without_catalog.append(
                {"method": row["method"], "path": row["path"],
                 "kind": "section", "id": section})
        if (row.get("resource") or "").startswith("action.") \
                and row["resource"][len("action."):] not in actions:
            guarded_without_catalog.append(
                {"method": row["method"], "path": row["path"],
                 "kind": "action", "id": row["resource"]})
    report["catalog_without_guard"] = catalog_without_guard
    report["guarded_without_catalog"] = guarded_without_catalog
    report["catalog_counts"] = {
        "sections": len(sections), "params": len(params),
        "actions": len(actions),
    }
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(ROOT))
    parser.add_argument("--out", default=None)
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    root = Path(args.root).resolve()
    report = diff_against_catalog(inventory(root), root)
    payload = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out:
        Path(args.out).write_text(payload + "\n", encoding="utf-8")
    else:
        print(payload)
    if args.check:
        return 0 if not report["guarded_without_catalog"] else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
