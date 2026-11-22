"""MOD-ACL-UX-01 M4C C3 — durable ACL-audit (без второй таблицы).

Контракт: plans/features/mod-acl-ux-01/evidence/m4c/c3-contract-2026-11-22.md
§4 (DDL 1), §6 (audit-контракт), §10.1 п.4-5, 9.

Проверяется:
  * builder/parser: allowlist полей, домены entity/op, каноническая
    сериализация (entity-фильтр LIKE точен), malformed-строки не скрывают
    факт изменения;
  * permissions_snapshot/permisssions_diff: полный объект create/delete и
    минимальный diff update;
  * размер: редкая destructive-операция роли ≤ 64 KB, без молчаливых
    усечений;
  * private metadata: значения/prompt/last4/raw-ключи не попадают в событие
    (builder принимает только allowlist-поля; param events — только роли);
  * DDL: единственное изменение — CHECK `chat_lore_history.field` += access;
    SQLite schema 48 не меняется (chat_lore_history — PG-only);
  * insert_access_audit: field='access', old_value='' (fail-closed —
  исключение прокидывается).
"""
import json

import pytest

from services import acl_audit
from services.permissions import Permissions


class _Conn:
    def __init__(self):
        self.calls = []

    async def execute(self, sql, *args):
        self.calls.append((sql, args))
        return "INSERT 0 1"


def test_build_event_allowlist_and_domains():
    event = acl_audit.build_event(
        entity=acl_audit.ENTITY_ROLE, op=acl_audit.OP_UPDATE,
        role_name="custom", before={"sections": ["limits"]},
        after={"added": {"sections": ["flags"]}})
    assert set(event) == {
        "v", "entity", "op", "role_name", "telegram_id", "key",
        "before", "after"}
    assert event["v"] == 1
    with pytest.raises(ValueError):
        acl_audit.build_event(entity="bogus", op=acl_audit.OP_CREATE)
    with pytest.raises(ValueError):
        acl_audit.build_event(entity=acl_audit.ENTITY_ROLE, op="bogus")
    with pytest.raises(ValueError):
        acl_audit.build_event(entity=acl_audit.ENTITY_ROLE,
                              op=acl_audit.OP_CREATE, before=["not", "dict"])


def test_serialize_is_canonical_and_filter_exact():
    event = acl_audit.build_event(
        entity=acl_audit.ENTITY_PARAM_GLOBAL, op=acl_audit.OP_UPDATE,
        key="limits.search_max_symbols",
        before={"view_roles": ["moderator", "local_admin"],
                "edit_roles": ["local_admin"]},
        after={"view_roles": ["moderator", "local_admin"],
               "edit_roles": ["moderator", "local_admin"]})
    raw = acl_audit.serialize_event(event)
    assert ',"entity":"param_global",' in raw
    assert '": ' not in raw          # компактные разделители
    assert raw == acl_audit.serialize_event(dict(reversed(list(event.items()))))
    assert json.loads(raw) == event
    with pytest.raises(ValueError):
        acl_audit.serialize_event({**event, "raw_key": "secret"})


def test_parse_event_valid_and_malformed():
    good = acl_audit.build_event(
        entity=acl_audit.ENTITY_CHAT_ADMIN, op=acl_audit.OP_CREATE,
        telegram_id=777, after={"role_name": "moderator"})
    parsed = acl_audit.parse_event(acl_audit.serialize_event(good))
    assert parsed["entity"] == "chat_admin"
    assert parsed["telegram_id"] == 777
    assert parsed["after"] == {"role_name": "moderator"}
    assert acl_audit.parse_event("not-json") is None
    assert acl_audit.parse_event('{"entity":"bogus","op":"create"}') is None
    assert acl_audit.parse_event('{"entity":"role","op":"create",'
                                 '"before":[]}') is None
    # Неизвестные поля отбрасываются, а не ломают разбор.
    dirty = json.dumps({"v": 1, "entity": "role", "op": "delete",
                        "role_name": "x", "before": {"sections": []},
                        "after": None, "_prompt": "DO_NOT_LEAK"})
    parsed = acl_audit.parse_event(dirty)
    assert parsed is not None and "_prompt" not in parsed


def test_permissions_snapshot_and_diff():
    before = {"sections": ["limits", "access"], "params": ["a"],
              "keys": [], "actions": ["control.stop"], "wildcard": False}
    after = {"sections": ["limits", "flags"], "params": ["a", "b"],
             "keys": ["keys.llm_api_key"], "actions": [],
             "wildcard": True}
    snap = acl_audit.permissions_snapshot(before)
    assert snap == {"wildcard": False, "sections": ["access", "limits"],
                    "params": ["a"], "keys": [], "actions": ["control.stop"]}
    diff = acl_audit.permissions_diff(before, after)
    assert diff["wildcard"] == {"before": False, "after": True}
    assert diff["added"] == {"sections": ["flags"], "params": ["b"],
                             "keys": ["keys.llm_api_key"]}
    assert diff["removed"] == {"sections": ["access"],
                               "actions": ["control.stop"]}
    assert acl_audit.permissions_diff(before, before) == {}
    # Полный create-снимок всегда содержит wildcard (даже False).
    full = acl_audit.permissions_snapshot({})
    assert list(full) == ["wildcard", "sections", "params", "keys", "actions"]
    assert full["wildcard"] is False


def test_destructive_role_event_size_bound():
    """§4.2: create/delete роли — полный grants-объект; верхняя граница
    ≤64 KB. Тест ловит случайное попадание значений/prompt в снимок."""
    perms = Permissions.from_dict({
        "sections": ["limits", "flags", "reactions", "content", "memory",
                     "chat_lore", "access"],
        "params": [f"limits.param_{i}" for i in range(300)],
        "keys": ["keys.llm_api_key", "keys.image_api_key"],
        "actions": [f"action_{i}" for i in range(200)],
        "wildcard": False,
    }).to_dict()
    event = acl_audit.build_event(
        entity=acl_audit.ENTITY_ROLE, op=acl_audit.OP_DELETE,
        role_name="large_custom", before=acl_audit.permissions_snapshot(perms),
        after=None)
    raw = acl_audit.serialize_event(event)
    assert 0 < len(raw.encode("utf-8")) <= 64 * 1024
    # Никаких значений параметров: только имена грантов.
    assert "SENTINEL_VALUE" not in raw and "last4" not in raw


def test_param_event_has_no_values_or_prompts():
    event = acl_audit.build_event(
        entity=acl_audit.ENTITY_PARAM_CHAT, op=acl_audit.OP_RESET,
        key="prompts.summary_system_prompt",
        before={"view_roles": ["local_admin"], "edit_roles": []},
        after=None)
    raw = acl_audit.serialize_event(event)
    assert "SENTINEL_PROMPT" not in raw
    assert "last4" not in raw
    assert set(json.loads(raw)) == set(
        ["v", "entity", "op", "role_name", "telegram_id", "key", "before",
         "after"])


@pytest.mark.asyncio
async def test_insert_access_audit_columns_and_old_value_empty():
    conn = _Conn()
    event = acl_audit.build_event(
        entity=acl_audit.ENTITY_ADMIN, op=acl_audit.OP_CREATE,
        telegram_id=4242, after={"role_name": "moderator"})
    await acl_audit.insert_access_audit(conn, chat_id=0, changed_by=42,
                                        event=event)
    sql, args = conn.calls[0]
    assert "chat_lore_history" in sql
    assert args[0] == 0
    assert args[1] == "access"
    assert args[2] == 42
    assert args[3] == ""            # old_value не используется
    assert json.loads(args[4])["entity"] == "admin"


@pytest.mark.asyncio
async def test_insert_access_audit_propagates_failure_fail_closed():
    class _Boom(_Conn):
        async def execute(self, sql, *args):
            raise RuntimeError("audit insert failed")

    event = acl_audit.build_event(
        entity=acl_audit.ENTITY_ROLE, op=acl_audit.OP_DELETE,
        role_name="x", before={"sections": []}, after=None)
    with pytest.raises(RuntimeError):
        await acl_audit.insert_access_audit(_Boom(), chat_id=0,
                                            changed_by=1, event=event)


def test_ddl_single_change_and_sqlite_schema_unchanged():
    import services.database as database
    import services.pg_db as pg_db

    ddl = "\n".join(pg_db.DDL_STATEMENTS)
    add = [s for s in pg_db.DDL_STATEMENTS
           if "ADD CONSTRAINT chat_lore_history_field_check" in s]
    assert len(add) == 1
    assert "'access'" in add[0]
    assert "CREATE TABLE IF NOT EXISTS access_audit" not in ddl
    assert "CREATE INDEX IF NOT EXISTS idx_access_audit" not in ddl
    # SQLite schema не меняется: chat_lore_history существует только в PG.
    assert database._SCHEMA_VERSION_RANDOM_BATCH_PROVENANCE == 48
    src = open(database.__file__, encoding="utf-8").read()
    assert "CREATE TABLE IF NOT EXISTS chat_lore_history" not in src


def test_migration_idempotent_and_rollback_compatible():
    """DDL 1: только superset-CHECK; повторный старт no-op; DROP IF EXISTS
    означает идемпотентность, а старый код (без 'access') совместим с
    расширенным constraint и не требует downgrade."""
    import re

    import services.pg_db as pg_db

    drops = [s for s in pg_db.DDL_STATEMENTS
             if "DROP CONSTRAINT IF EXISTS chat_lore_history_field_check" in s]
    adds = [s for s in pg_db.DDL_STATEMENTS
            if "ADD CONSTRAINT chat_lore_history_field_check" in s]
    assert len(drops) == 1 and len(adds) == 1
    values = set(re.findall(r"'([a-z_]+)'", adds[0]))
    assert values == {
        "manual", "auto", "auto_enabled", "auto_period_hours",
        "auto_window_hours", "remap", "chat_admin", "chat_params",
        "chat_keys", "gates", "access"}
    # Никаких destructive операций с данными/схемой в этом DDL.
    assert "DELETE" not in adds[0].upper()
    assert "DROP TABLE" not in adds[0].upper()
    assert "DROP COLUMN" not in adds[0].upper()
    # Все существующие значения по-прежнему валидны (superset).
    assert {"manual", "gates"} < values
