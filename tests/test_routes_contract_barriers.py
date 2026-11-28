"""Самопроверка контракта маршрутов (corrective r1: F-BAR-01/02/03).

Проверяем именно свойства нового механизма:
  * дубль ``(path, methods)`` и два AST-декоратора с одним ключом ловятся
    (сценарий ревьюера M5: ``get_admins_shadow`` без RBAC перед оригиналом);
  * guard-эвристика видит inline-проверки, названные по соглашениям
    ``_require*``/``_assert*``/``*_guard``/``*_rights``/``*_admin``;
  * манифест действительно фиксирует эти проверки у живых маршрутов;
  * CLI ``python -m tests.routes_contract --check`` и рендер/эмиссия
    детерминированы (байт-идентичны).
"""
from __future__ import annotations

import subprocess
import sys

import pytest

from tests import routes_contract as rc


def _row(path: str, methods, checks=(), init_data: bool = True) -> dict:
    return {
        "path": path,
        "methods": list(methods),
        "init_data": init_data,
        "checks": list(checks),
    }


class TestDuplicateRoutes:
    def test_shadow_route_same_path_and_method_is_rejected(self):
        # Ровно сценарий M5: более слабый обработчик (без requires_permission)
        # объявлен перед оригиналом; FastAPI диспатчит первый.
        rows = [
            _row("/admins", ["GET"], ["get_tma_user"]),  # get_admins_shadow
            _row("/admins", ["GET"],
                 ["get_tma_user", "requires_permission:access"]),  # get_admins
        ]
        assert rc.duplicate_route_keys(rows) == [("/admins", ("GET",))]
        with pytest.raises(AssertionError, match="неуникальные"):
            rc.assert_routes_unique(rows, "тест: дубль маршрута")

    def test_ast_duplicate_decorators_are_rejected(self):
        source = (
            "from fastapi import APIRouter\n"
            "api_router = APIRouter()\n"
            "\n"
            "@api_router.get('/admins')\n"
            "async def get_admins_shadow():\n"
            "    return []\n"
            "\n"
            "@api_router.get('/admins')\n"
            "async def get_admins():\n"
            "    return []\n"
        )
        records = rc.ast_route_records(source)
        assert [rec["handler"] for rec in records] == [
            "get_admins_shadow", "get_admins"]
        rows = [{"path": rec["path"], "methods": [rec["method"]]}
                for rec in records]
        assert rc.duplicate_route_keys(rows) == [("/admins", ("GET",))]
        with pytest.raises(AssertionError, match="AST"):
            rc.assert_routes_unique(rows, "AST-декораторы routes.py")

    def test_overlapping_methods_are_rejected(self):
        rows = [_row("/probe", ["GET", "POST"]), _row("/probe", ["GET"])]
        with pytest.raises(AssertionError, match="дважды"):
            rc.assert_routes_unique(rows, "тест: пересечение методов")

    def test_same_path_with_distinct_methods_is_allowed(self):
        rows = [_row("/admins", ["GET"]), _row("/admins", ["POST"])]
        assert rc.duplicate_route_keys(rows) == []
        assert rc.overlapping_route_methods(rows) == []
        rc.assert_routes_unique(rows, "тест: разные методы")

    def test_live_routes_are_unique(self):
        rows = rc.collect_routes()
        assert rows
        assert rc.duplicate_route_keys(rows) == []
        assert rc.overlapping_route_methods(rows) == []
        assert len(rows) == len(rc.load_manifest()["routes"])


class TestGuardHeuristic:
    @pytest.mark.parametrize("name", [
        "_prompt_hidden_admin",
        "_random_selector_guard",
        "_recheck_config_chat_rights",
        "_recheck_meme_rights",
        "_meme_template_guard",
        "_require_chat_access",
        "_prompt_require_edit",
        "requires_permission",
        "requires_global_admin",
        "_ctx_global_admin",
        "user_is_global_admin",
        "_assert_some_access",
        # corrective r2 (F-BAR-07): чат-изоляция и аналогичные access-хелперы.
        "can_access_chat",
        "can_edit_param",
        "can_view_key_value",
        "can_view_param",
        "gate_authorization",
        "guard_admin_lockout",
        "guard_last_wildcard",
        "validate_permissions",
        "match_permission",
    ])
    def test_access_check_names_are_visible(self, name):
        assert rc.is_guard_call_name(name), name

    @pytest.mark.parametrize("name", [
        "remove_admin",
        "upsert_admin",
        "add_admin",
        "get_cache",
        "required",
        "build_prompt_catalog",
        "gate_snapshot",
        "gate_state",
        "validate_value_rule",
        "get_permissions",
        "_persona_access",   # резолвер ctx, не enforcement-проверка
    ])
    def test_business_helpers_are_not_guards(self, name):
        assert not rc.is_guard_call_name(name), name

    @pytest.mark.parametrize("name", [
        "prompt_access",     # модуль, а не guard
        "global_access",     # локальная переменная
        "can_write",         # локальная переменная (capability)
        "can_read",
        "can_edit",
        "_persona_access",
    ])
    def test_references_are_not_guard_callbacks(self, name):
        # Callback-правило не должно ловить модули/локальные переменные.
        assert not rc._is_guard_callback_name(name), name

    def test_can_access_chat_gate_is_derived_from_handler_source(self):
        # X1 (F-BAR-07) на уровне вывода checks: снятие chat-isolation
        # gate меняет производный набор, значит контракт обязан упасть.
        import ast as _ast

        with_gate = _ast.parse(
            "async def handler(request, user):\n"
            "    ctx = await _persona_access(request, user, None)\n"
            "    if not access_srv.can_access_chat(ctx, chat_id):\n"
            "        raise HTTPException(status_code=403)\n"
        ).body[0]
        without_gate = _ast.parse(
            "async def handler(request, user):\n"
            "    ctx = await _persona_access(request, user, None)\n"
        ).body[0]
        assert "can_access_chat" in rc._source_checks(with_gate)
        assert "can_access_chat" not in rc._source_checks(without_gate)

    def test_manifest_records_former_inline_guards(self):
        # F-BAR-02: раньше эти вызовы были невидимы контракту (M6 проходил
        # зелёным). Теперь они обязаны быть в объявленном манифесте.
        declared = {(row["path"], tuple(row["methods"])): row["checks"]
                    for row in rc.load_manifest()["routes"]}
        assert "_prompt_hidden_admin" in declared[("/prompts/catalog", ("GET",))]
        assert "_meme_template_guard" in declared[("/config", ("POST",))]
        assert "_random_selector_guard" in declared[("/config", ("POST",))]
        assert "_recheck_config_chat_rights" in declared[("/config", ("POST",))]
        assert "_meme_template_guard" in declared[
            ("/initiative/meme-settings", ("POST",))]
        assert "_recheck_meme_rights" in declared[
            ("/initiative/meme-settings", ("POST",))]

    def test_manifest_records_chat_isolation_checks(self):
        # F-BAR-07: 7 маршрутов, где чат-изоляция держится на
        # access_srv.can_access_chat, обязаны это фиксировать в контракте.
        declared = {(row["path"], tuple(row["methods"])): row["checks"]
                    for row in rc.load_manifest()["routes"]}
        for key in [
            ("/config/time", ("GET",)),
            ("/config/time", ("POST",)),
            ("/direct/context-diagnostics", ("GET",)),
            ("/direct/turn-diagnostics", ("GET",)),
            ("/config/keys/status", ("GET",)),
            ("/config/overrides-map", ("GET",)),
            ("/status", ("GET",)),
        ]:
            assert "can_access_chat" in declared[key], key

    def test_manifest_records_analogous_access_helpers(self):
        declared = {(row["path"], tuple(row["methods"])): row["checks"]
                    for row in rc.load_manifest()["routes"]}
        assert "gate_authorization" in declared[("/config", ("GET",))]
        assert "guard_admin_lockout" in declared[("/admins", ("POST",))]
        assert "guard_last_wildcard" in declared[("/roles", ("POST",))]
        assert "validate_permissions" in declared[("/roles", ("POST",))]
        assert "match_permission" in declared[("/roles/tree", ("GET",))]


class TestManifestEmission:
    def test_render_matches_committed_manifest(self):
        committed = rc.MANIFEST_PATH.read_text(encoding="utf-8")
        assert rc.render_manifest() == committed
        assert rc.manifest_mismatch() == []
        assert rc.check_manifest() == 0

    def test_emit_is_byte_identical_and_repeatable(self, tmp_path):
        committed = rc.MANIFEST_PATH.read_bytes()
        first = tmp_path / "routes-contract-1.json"
        second = tmp_path / "routes-contract-2.json"
        rc.emit_manifest(first)
        rc.emit_manifest(second)
        assert first.read_bytes() == committed
        assert second.read_bytes() == committed

    def test_module_cli_check_exits_zero(self):
        proc = subprocess.run(
            [sys.executable, "-m", "tests.routes_contract", "--check"],
            cwd=str(rc.ROOT), capture_output=True, text=True, timeout=180,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "CHECK OK" in proc.stdout
