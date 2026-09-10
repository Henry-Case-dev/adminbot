"""Редизайн 10.5 (T-1141/T-1142) — роль-админ: guards rename/delete.

Маркеры + unit чистых guard-функций и наличие backend-методов каскада.
"""
import re

from web.api.routes import _is_builtin_role, _is_superuser_role

_ROUTES = open("web/api/routes.py", encoding="utf-8").read()
_CACHE = open("services/config_cache.py", encoding="utf-8").read()


class TestRoleGuards:
    def test_superuser_by_name(self):
        assert _is_superuser_role("admin", None)
        assert _is_superuser_role("global_admin", None)
        assert _is_superuser_role("superuser", None)
        assert not _is_superuser_role("viewer", None)

    def test_superuser_by_role_type(self):
        assert _is_superuser_role("custom_x", {"role_type": "global_admin"})
        assert not _is_superuser_role("custom_x", {"role_type": "moderator"})

    def test_builtin_by_role_type(self):
        assert _is_builtin_role({"role_type": "local_admin"})
        assert _is_builtin_role({"role_type": "moderator"})
        assert _is_builtin_role({"role_type": "user"})
        assert not _is_builtin_role({"role_type": None})
        assert not _is_builtin_role(None)

    def test_endpoints_present(self):
        assert '@api_router.delete("/roles/{role_name}")' in _ROUTES
        assert '@api_router.post("/roles/{role_name}/rename")' in _ROUTES
        assert "class RoleRename(BaseModel)" in _ROUTES

    def test_delete_guards_order_and_codes(self):
        body = _ROUTES[_ROUTES.index("async def delete_role_endpoint"):]
        body = body[:body.index("async def rename_role_endpoint")]
        assert "status_code=403" in body            # superuser
        assert "встроенную роль нельзя удалить" in body  # builtin 409
        assert "role_usage" in body                 # занятость → 409
        assert "guard_last_wildcard" in body        # последняя wildcard
        assert "cache.delete_role" in body

    def test_rename_guards(self):
        body = _ROUTES[_ROUTES.index("async def rename_role_endpoint"):]
        body = body[:body.index("async def get_roles_tree")]
        assert "status_code=403" in body
        assert "встроенную роль нельзя переименовать" in body
        assert "role already" not in body
        assert "cache.rename_role" in body

    def test_config_cache_cascade_methods(self):
        assert "async def rename_role" in _CACHE
        assert "async def role_usage" in _CACHE
        assert "_scrub_param_permissions" in _CACHE
        # каскад: перенос роли в bot_admins + чистка param_permissions.
        rename = _CACHE[_CACHE.index("async def rename_role"):]
        assert "UPDATE bot_admins SET role_name" in rename
        assert "_scrub_param_permissions(conn, old_name)" in rename
        assert "DELETE FROM bot_roles WHERE role_name" in rename

    def test_no_new_ddl(self):
        # Инвариант: rename/delete не добавляют DDL (только DML в существующих
        # таблицах). Проверяем отсутствие CREATE/ALTER в новых методах.
        seg = _CACHE[_CACHE.index("async def rename_role"):]
        seg = seg[:seg.index("async def reload")]
        assert not re.search(r"\b(CREATE|ALTER)\s+TABLE", seg, re.I)
