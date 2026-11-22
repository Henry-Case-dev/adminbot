"""MOD-ACL-UX-01 M4C C3 — durable ACL-audit в существующей истории чата.

Событие хранится ОДНОЙ строкой `chat_lore_history`:
    field='access', chat_id=0 для глобальных сущностей (sentinel
    `GLOBAL_AUDIT_CHAT_ID`), реальный chat_id — для чатовых; `changed_by` —
    актор (NULL — только система); `old_value=''` всегда, полное событие —
    в `new_value` (единый формат create/update/delete, без второго).

Формат (allowlist; лишние поля невозможны — builder принимает только
именованные аргументы, parse отбрасывает неизвестные):
    {"v":1,"entity":"role|admin|chat_admin|param_global|param_chat",
     "op":"create|update|delete|rename|set|reset",
     "role_name":str|null,"telegram_id":int|null,"key":str|null,
     "before":dict|null,"after":dict|null}

Privacy (BL-M4C-AUDIT-PROMPT): сюда НЕ попадают значения параметров,
prompt-тексты, raw-ключи, last4, тела секретов, chat_params.overrides,
содержимое чужих настроек. Только метаданные прав и минимальные диффы.

Fail-closed: вставка идёт В ТОЙ ЖЕ транзакции, что мутация; ошибка вставки
откатывает мутацию (см. config_cache/access/chat_params).
"""
import json

from services.permissions import Permissions

AUDIT_FIELD = "access"
EVENT_VERSION = 1

ENTITY_ROLE = "role"
ENTITY_ADMIN = "admin"
ENTITY_CHAT_ADMIN = "chat_admin"
ENTITY_PARAM_GLOBAL = "param_global"
ENTITY_PARAM_CHAT = "param_chat"
ENTITY_DOMAIN: tuple[str, ...] = (
    ENTITY_ROLE, ENTITY_ADMIN, ENTITY_CHAT_ADMIN,
    ENTITY_PARAM_GLOBAL, ENTITY_PARAM_CHAT,
)

OP_CREATE = "create"
OP_UPDATE = "update"
OP_DELETE = "delete"
OP_RENAME = "rename"
OP_SET = "set"
OP_RESET = "reset"
OP_DOMAIN: tuple[str, ...] = (
    OP_CREATE, OP_UPDATE, OP_DELETE, OP_RENAME, OP_SET, OP_RESET,
)

_TOP_FIELDS = ("v", "entity", "op", "role_name", "telegram_id", "key",
               "before", "after")
_PERMISSION_FIELDS = ("sections", "params", "keys", "actions")

INSERT_ACCESS_AUDIT_SQL = (
    "INSERT INTO chat_lore_history (chat_id, field, changed_by, old_value, "
    "new_value) VALUES ($1, $2, $3, $4, $5)"
)


def build_event(*, entity: str, op: str, role_name: str | None = None,
                telegram_id: int | None = None, key: str | None = None,
                before: dict | None = None, after: dict | None = None) -> dict:
    """Собрать событие audit из allowlist-полей (никаких **kwargs).

    Домены entity/op проверяются здесь, чтобы некорректное событие не
    попало в БД и не «сломало» фильтр чтения. before/after — только
    dict|None; вызывающий отвечает за их минимальность (см. §6.1 контракта).
    """
    if entity not in ENTITY_DOMAIN:
        raise ValueError(f"audit: неизвестная entity {entity!r}")
    if op not in OP_DOMAIN:
        raise ValueError(f"audit: неизвестная op {op!r}")
    if before is not None and not isinstance(before, dict):
        raise ValueError("audit: before должен быть объектом или None")
    if after is not None and not isinstance(after, dict):
        raise ValueError("audit: after должен быть объектом или None")
    if telegram_id is not None:
        telegram_id = int(telegram_id)
    return {
        "v": EVENT_VERSION,
        "entity": entity,
        "op": op,
        "role_name": role_name,
        "telegram_id": telegram_id,
        "key": key,
        "before": before,
        "after": after,
    }


def serialize_event(event: dict) -> str:
    """Каноническая компактная сериализация (entity-фильтр LIKE точен)."""
    if not isinstance(event, dict):
        raise ValueError("audit: событие должно быть объектом")
    extra = set(event) - set(_TOP_FIELDS)
    if extra:
        raise ValueError(f"audit: поля вне allowlist: {sorted(extra)}")
    for name in ("entity", "op"):
        if event.get(name) not in (ENTITY_DOMAIN if name == "entity"
                                   else OP_DOMAIN):
            raise ValueError(f"audit: недопустимое {name}: {event.get(name)!r}")
    return json.dumps(event, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


async def insert_access_audit(conn, *, chat_id: int, changed_by: int | None,
                              event: dict) -> None:
    """Вставить строку аудита на УЖЕ открытом коннекте транзакции мутации.

    Ошибку не глотает: вызывающий владеет rollback (fail-closed).
    """
    await conn.execute(INSERT_ACCESS_AUDIT_SQL, int(chat_id), AUDIT_FIELD,
                       changed_by, "", serialize_event(event))


def parse_event(raw) -> dict | None:
    """Разобрать new_value строки audit.

    None — JSON/форма не разобрались (API покажет malformed:true и факт
    изменения не скроет). Неизвестные поля отбрасываются; отсутствующие
    обязательные — malformed.
    """
    if isinstance(raw, (bytes, bytearray)):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError:
            return None
    if isinstance(raw, str):
        try:
            loaded = json.loads(raw)
        except ValueError:
            return None
    else:
        loaded = raw
    if not isinstance(loaded, dict):
        return None
    if loaded.get("entity") not in ENTITY_DOMAIN:
        return None
    if loaded.get("op") not in OP_DOMAIN:
        return None
    before = loaded.get("before")
    after = loaded.get("after")
    if before is not None and not isinstance(before, dict):
        return None
    if after is not None and not isinstance(after, dict):
        return None
    telegram_id = loaded.get("telegram_id")
    if telegram_id is not None:
        try:
            telegram_id = int(telegram_id)
        except (TypeError, ValueError):
            return None
    return {
        "v": EVENT_VERSION,
        "entity": loaded["entity"],
        "op": loaded["op"],
        "role_name": loaded.get("role_name"),
        "telegram_id": telegram_id,
        "key": loaded.get("key"),
        "before": before,
        "after": after,
    }


def permissions_snapshot(permissions: dict | None) -> dict:
    """Полный объект прав для create/delete роли: wildcard всегда присутствует."""
    perms = Permissions.from_dict(permissions or {}).to_dict()
    return {
        "wildcard": bool(perms.get("wildcard", False)),
        "sections": list(perms.get("sections") or []),
        "params": list(perms.get("params") or []),
        "keys": list(perms.get("keys") or []),
        "actions": list(perms.get("actions") or []),
    }


def permissions_diff(before: dict | None, after: dict | None) -> dict:
    """Минимальный diff update-роли: wildcard + added/removed по массивам.

    Возвращает {} для реального no-op (вызывающий такой audit не пишет).
    """
    old = permissions_snapshot(before)
    new = permissions_snapshot(after)
    out: dict = {}
    if old["wildcard"] != new["wildcard"]:
        out["wildcard"] = {"before": old["wildcard"],
                           "after": new["wildcard"]}
    added: dict = {}
    removed: dict = {}
    for field in _PERMISSION_FIELDS:
        old_set = set(old[field])
        new_set = set(new[field])
        plus = sorted(new_set - old_set)
        minus = sorted(old_set - new_set)
        if plus:
            added[field] = plus
        if minus:
            removed[field] = minus
    if added:
        out["added"] = added
    if removed:
        out["removed"] = removed
    return out
