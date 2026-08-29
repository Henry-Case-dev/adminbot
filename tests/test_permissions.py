"""Epic 85 (T-635) — тесты RBAC v2 (84.14): permissions-объект, матчинг
requires_permission (exact/секция/wildcard/отказ), guard последней wildcard.

DoD 84.16.2 п.13: матчинг, сид v2 (через pg_db DEFAULT_ROLES), guard 409.
"""
import pytest

from services.permissions import (
    ACTIONS_TREE,
    Permissions,
    RoleGuardError,
    guard_last_wildcard,
    requires_permission,
    validate_permissions,
)
from services.pg_db import DEFAULT_ROLES


def _perms(**kw) -> Permissions:
    return Permissions.from_dict(kw)


class TestPermissionsObject:
    def test_from_dict_to_dict_roundtrip(self):
        data = {
            "sections": ["limits", "keys"],
            "params": ["limits.search_max_symbols"],
            "keys": ["keys.groq_api_key"],
            "actions": ["control.restart", "edit_info"],
            "wildcard": True,
        }
        perms = Permissions.from_dict(data)
        out = perms.to_dict()
        assert out["sections"] == ["keys", "limits"]
        assert out["params"] == ["limits.search_max_symbols"]
        assert out["keys"] == ["keys.groq_api_key"]
        assert out["actions"] == ["control.restart", "edit_info"]
        assert out["wildcard"] is True

    def test_empty_and_junk_tolerated(self):
        assert Permissions.from_dict(None).wildcard is False
        assert Permissions.from_dict({"sections": "limits"}).sections \
            == frozenset()
        assert Permissions.from_dict({"wildcard": 1}).wildcard is True

    def test_empty_permissions_has_any_false(self):
        assert _perms().has_any() is False
        assert _perms(sections=["limits"]).has_any() is True


class TestMatching:
    """84.14.2: wildcard → exact → секция-родитель → отказ."""

    def test_wildcard_allows_everything(self):
        admin = _perms(wildcard=True)
        for req in ("section.limits", "param.limits.search_max_symbols",
                    "key.keys.groq_api_key", "action.control.restart",
                    "edit_info", "access"):
            assert requires_permission(admin, req), req

    def test_exact_section(self):
        perms = _perms(sections=["access"])
        assert requires_permission(perms, "section.access")
        assert requires_permission(perms, "access")  # голое legacy-имя
        assert not requires_permission(perms, "section.limits")

    def test_exact_param(self):
        perms = _perms(params=["limits.search_max_symbols"])
        assert requires_permission(perms, "param.limits.search_max_symbols")
        assert requires_permission(perms, "limits.search_max_symbols")
        assert not requires_permission(perms, "param.limits.other")

    def test_exact_key(self):
        perms = _perms(keys=["keys.groq_api_key"])
        assert requires_permission(perms, "key.keys.groq_api_key")
        assert not requires_permission(perms, "key.keys.tavily_api_key")

    def test_exact_action(self):
        perms = _perms(actions=["control.restart"])
        assert requires_permission(perms, "action.control.restart")
        assert not requires_permission(perms, "action.control.stop")

    def test_section_covers_params(self):
        perms = _perms(sections=["limits"])
        assert requires_permission(perms, "param.limits.search_max_symbols")
        assert requires_permission(perms, "param.limits.anything.else")
        assert not requires_permission(perms, "param.models.llm_timeout")

    def test_section_keys_covers_all_keys(self):
        perms = _perms(sections=["keys"])
        assert requires_permission(perms, "key.keys.groq_api_key")
        assert requires_permission(perms, "key.keys.any")
        assert not requires_permission(perms, "param.limits.x")

    def test_sections_do_not_cover_actions(self):
        """84.14.2: action.* секциями НЕ покрывается — только явные actions."""
        perms = _perms(sections=["limits", "keys", "access"])
        assert not requires_permission(perms, "action.control.restart")
        assert not requires_permission(perms, "edit_info")

    def test_bare_dotted_covered_by_section(self):
        """Без префикса: «limits.xyz» покрывается секцией limits."""
        perms = _perms(sections=["limits"])
        assert requires_permission(perms, "limits.xyz")

    def test_empty_required_and_unknown(self):
        perms = _perms(sections=["limits"])
        assert not requires_permission(perms, "")
        assert not requires_permission(perms, None)
        assert not requires_permission(perms, "section.nonexistent")

    def test_moderator_seed(self):
        mod = _perms(sections=["limits"],
                     actions=["control.restart", "control.stop",
                              "control.start"])
        assert requires_permission(mod, "param.limits.search_max_symbols")
        assert requires_permission(mod, "action.control.restart")
        assert not requires_permission(mod, "action.edit_info")
        assert not requires_permission(mod, "param.prompts.factcheck")
        assert not requires_permission(mod, "access")

    def test_user_seed_denies_all(self):
        user = _perms()
        assert not requires_permission(user, "section.limits")
        assert not requires_permission(user, "action.edit_info")
        assert not requires_permission(user, "key.keys.groq_api_key")

    def test_default_roles_seed_v2(self):
        """84.14.3: сид v2 из pg_db."""
        by_name = {r["role_name"]: r for r in DEFAULT_ROLES}
        admin = Permissions.from_dict(by_name["admin"]["permissions"])
        assert admin.wildcard
        mod = Permissions.from_dict(by_name["moderator"]["permissions"])
        assert requires_permission(mod, "action.control.restart")
        assert requires_permission(mod, "param.limits.x")
        assert not requires_permission(mod, "edit_info")
        user = Permissions.from_dict(by_name["user"]["permissions"])
        assert not user.has_any()


class TestActionsTree:
    def test_edit_info_and_control_mapped(self):
        ids = {a["id"] for a in ACTIONS_TREE}
        assert ids == {"edit_info", "control.restart", "control.stop",
                       "control.start"}
        for action in ACTIONS_TREE:
            assert action["title"]


class TestValidation:
    def test_valid_passes(self):
        validate_permissions(
            {"sections": ["limits"], "wildcard": False},
            known_sections={"limits", "keys"})

    def test_unknown_section_raises(self):
        with pytest.raises(ValueError, match="неизвестная секция"):
            validate_permissions({"sections": ["nope"]},
                                 known_sections={"limits"})

    def test_unknown_key_raises(self):
        with pytest.raises(ValueError, match="неизвестный ключ"):
            validate_permissions({"keys": ["keys.nope"]},
                                 known_keys={"keys.groq_api_key"})

    def test_unknown_param_raises(self):
        with pytest.raises(ValueError, match="неизвестный параметр"):
            validate_permissions({"params": ["limits.nope"]},
                                 known_params={"limits.search_max_symbols"})

    def test_wildcard_not_bool_raises(self):
        with pytest.raises(ValueError, match="wildcard"):
            validate_permissions({"wildcard": "yes"})

    def test_not_dict_raises(self):
        with pytest.raises(ValueError):
            validate_permissions(["limits"])


class TestGuard:
    """84.14.4: нельзя удалить/заблокировать последнюю wildcard-роль (409)."""

    def _roles(self):
        return {
            "admin": _perms(wildcard=True),
            "moderator": _perms(sections=["limits"]),
            "user": _perms(),
        }

    def test_delete_last_wildcard_raises_409(self):
        roles = self._roles()
        with pytest.raises(RoleGuardError) as exc:
            guard_last_wildcard(roles, "admin", None)
        assert exc.value.status_code == 409

    def test_strip_wildcard_from_last_raises(self):
        roles = self._roles()
        with pytest.raises(RoleGuardError):
            guard_last_wildcard(roles, "admin", _perms(sections=["limits"]))

    def test_keep_wildcard_ok(self):
        roles = self._roles()
        guard_last_wildcard(roles, "admin", _perms(wildcard=True))

    def test_two_wildcard_roles_delete_one_ok(self):
        roles = self._roles()
        roles["owner"] = _perms(wildcard=True)
        guard_last_wildcard(roles, "admin", None)
        guard_last_wildcard(roles, "admin", _perms())

    def test_non_wildcard_role_never_guarded(self):
        roles = self._roles()
        guard_last_wildcard(roles, "moderator", None)
        guard_last_wildcard(roles, "moderator", _perms(wildcard=True))
        guard_last_wildcard(roles, "user", _perms())

    def test_unknown_role_never_guarded(self):
        roles = self._roles()
        guard_last_wildcard(roles, "ghost", None)
