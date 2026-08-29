"""Epic 85 (84.14) — RBAC v2: гранулярные permissions-объект и матчинг.

Схема permissions (84.14.1):
    {
      "sections": ["limits", "prompts", "models", "keys", "access"],
      "params":   ["limits.search_max_symbols", "limits.chat_cooldown_seconds"],
      "keys":     ["keys.groq", "keys.tavily"],
      "actions":  ["control.restart", "control.stop", "control.start", "edit_info"],
      "wildcard": false
    }

Единый неймспейс (84.14.1): section.<id> (в sections — голый id),
param.<category>.<key> (полный ключ bot_settings), key.<category>.<key>
(конкретный ключ категории keys), action.<id> (в массиве actions — голый id).

Правила матчинга requires_permission (84.14.2):
  1. wildcard == true → да (всё);
  2. точное совпадение в соответствующей группе;
  3. родительская секция покрывает вложенные param./key.-права
     (param.<cat>.* покрыт секцией <cat>; любой ключ категории keys покрыт
     секцией keys; action.* секциями НЕ покрывается);
  4. иначе → отказ.

Guard (84.14.4): нельзя удалить/заблокировать последнюю роль с
wildcard:true → RoleGuardError (status_code 409 на уровне API).
"""
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

# ── Неймспейсы (84.14.1) ────────────────────────────────────────────────────
NS_SECTION = "section"
NS_PARAM = "param"
NS_KEY = "key"
NS_ACTION = "action"

# Действия (84.14.1/84.15.2): маппинг для /api/roles/tree (T-640).
ACTIONS_TREE: tuple[dict[str, str], ...] = (
    {"id": "edit_info", "title": "Редактировать «Как это работает»"},
    {"id": "control.restart", "title": "Перезапуск бота"},
    {"id": "control.stop", "title": "Остановка бота"},
    {"id": "control.start", "title": "Запуск бота"},
)

ACTION_IDS: frozenset[str] = frozenset(a["id"] for a in ACTIONS_TREE)

# Категория keys — «все ключи»; секция keys покрывает любой key.* (84.14.2).
SECTION_KEYS = "keys"


class RoleGuardError(Exception):
    """Нельзя оставить систему без роли с wildcard:true (лок-аут)."""

    def __init__(self, message: str = "нельзя удалить/снять wildcard с "
                                      "последней роли с полным доступом"):
        super().__init__(message)
        self.status_code = 409


@dataclass(frozen=True)
class Permissions:
    """Иммутабельный permissions-объект роли."""

    sections: frozenset[str] = frozenset()
    params: frozenset[str] = frozenset()
    keys: frozenset[str] = frozenset()
    actions: frozenset[str] = frozenset()
    wildcard: bool = False

    @classmethod
    def from_dict(cls, data: dict | None) -> "Permissions":
        """Десериализация из JSONB-объекта БД (устойчиво к мусору)."""
        if not isinstance(data, dict):
            data = {}
        return cls(
            sections=frozenset(_as_strs(data.get("sections"))),
            params=frozenset(_as_strs(data.get("params"))),
            keys=frozenset(_as_strs(data.get("keys"))),
            actions=frozenset(_as_strs(data.get("actions"))),
            wildcard=bool(data.get("wildcard", False)),
        )

    def to_dict(self) -> dict:
        """Сериализация в JSONB (сортированные списки — детерминизм)."""
        out: dict[str, Any] = {
            "sections": sorted(self.sections),
            "params": sorted(self.params),
            "keys": sorted(self.keys),
            "actions": sorted(self.actions),
        }
        if self.wildcard:
            out["wildcard"] = True
        return out

    def has_any(self) -> bool:
        return bool(self.sections or self.params or self.keys or self.actions
                    or self.wildcard)


def _as_strs(value) -> list[str]:
    if not isinstance(value, (list, tuple, set)):
        return []
    return [str(v) for v in value if str(v).strip()]


def requires_permission(perms: Permissions, required: str) -> bool:
    """Матчинг по 84.14.2: wildcard → exact → секция-родитель → отказ.

    `required` — неймспейсная форма: section.<id> / param.<cat>.<key> /
    key.<cat>.<key> / action.<id>; бонус: голые формы тоже работают
    (legacy-имена 84.3: «access»/«limits» → секции; «edit_info» → действия;
    «limits.search_max_symbols» без префикса → params).
    """
    if not required:
        return False
    required = required.strip()
    if perms.wildcard:
        return True
    if required.startswith(f"{NS_SECTION}."):
        return required[len(NS_SECTION) + 1:] in perms.sections
    if required.startswith(f"{NS_PARAM}."):
        full = required[len(NS_PARAM) + 1:]
        if full in perms.params:
            return True
        return full.split(".")[0] in perms.sections
    if required.startswith(f"{NS_KEY}."):
        full = required[len(NS_KEY) + 1:]
        if full in perms.keys:
            return True
        return full.split(".")[0] in perms.sections
    if required.startswith(f"{NS_ACTION}."):
        return required[len(NS_ACTION) + 1:] in perms.actions
    # голые формы (совместимость)
    if "." in required:
        if required in perms.params or required in perms.keys:
            return True
        return required.split(".")[0] in perms.sections
    return required in perms.actions or required in perms.sections


def validate_permissions(data: dict, known_sections: set[str] | None = None,
                         known_params: set[str] | None = None,
                         known_keys: set[str] | None = None,
                         known_actions: set[str] | None = None) -> None:
    """Валидация против каталога (84.14.4): неизвестный id → ValueError
    (422 на уровне API). known_* — из param_catalog/ACTIONS_TREE."""
    if not isinstance(data, dict):
        raise ValueError("permissions должен быть объектом")
    for group in ("sections", "params", "keys", "actions"):
        for value in _as_strs(data.get(group)):
            if group == "sections" and known_sections is not None \
                    and value not in known_sections:
                raise ValueError(f"неизвестная секция: {value}")
            if group == "params" and known_params is not None \
                    and value not in known_params:
                raise ValueError(f"неизвестный параметр: {value}")
            if group == "keys" and known_keys is not None \
                    and value not in known_keys:
                raise ValueError(f"неизвестный ключ: {value}")
            if group == "actions" and known_actions is not None \
                    and value not in known_actions:
                raise ValueError(f"неизвестное действие: {value}")
    if "wildcard" in data and not isinstance(data["wildcard"], bool):
        raise ValueError("wildcard должен быть boolean")


def guard_last_wildcard(roles: dict[str, Permissions], target_role: str,
                        new_permissions: Permissions | None) -> None:
    """Guard (84.14.4): target_role удаляется (new_permissions=None) или
    теряет wildcard → в системе обязана остаться хотя бы одна wildcard-роль.
    Нарушение → RoleGuardError (409)."""
    wildcard_roles = {name for name, p in roles.items() if p.wildcard}
    if target_role not in wildcard_roles:
        return
    if new_permissions is not None and new_permissions.wildcard:
        return
    if len(wildcard_roles) <= 1:
        raise RoleGuardError()
