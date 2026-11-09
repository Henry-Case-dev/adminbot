"""MOD-ACL-UX-01 M2 — before/after impact report: OLD vs NEW effective state.

Показывает, у КАКОГО чата и какой capability изменится фактическое состояние
после перехода на канонический резолвер GLOBAL-дефолт → CHAT-override
(§2.1/§2.4-5 ТЗ MOD-ACL-UX-01). Ни один чат не «теряется» в проценте:
изменения перечислены поштучно.

Режимы
------
* ``--fixture <json>`` — детерминированный прогон на зафиксированном наборе
  (глобальные значения + строки чатов). Никакого I/O с БД; одинаковый вход →
  байт-в-байт одинаковый отчёт (используется тестом
  ``tests/test_mod_acl_ux_m2_resolver.py``).
* ``--database`` — READ-ONLY прогон по PostgreSQL: читаются только
  ``bot_settings`` / ``chat_profiles`` (SELECT). Ни одной записи, DDL, сида и
  миграции: DSN проверяется на доступность, но ``PgDatabase.init()``
  сознательно НЕ вызывается. Этот режим предназначен для production и
  выполняется DevOps как отдельный read-only шаг.

Семантика OLD (снята с кода ДО M2):
* модульный мастер (``chat_params.overrides[key]``) — override → глобал;
* ``experience`` — глобальная ось была ЗАПРЕТОМ: GLOBAL OFF глушил любой
  чат даже при явном chat ON (EXP-FIX-08);
* тяжёлые гейты (``chat_params.gates[f]``) — чат-гейт → явный глобальный
  ``flags.<f>_enabled`` (тихий veto) → master-fallback → глобальный флаг.

Семантика NEW — ``services.chat_params.resolve_*_capability`` (единственный
источник истины). Emergency env-оси (``MCA_*``) в отчёте показаны отдельной
колонкой: они перекрывают и OLD, и NEW, поэтому не создают «изменения».

Только stdout/``--out``; секретов нет (имена ключей и bool-значения).
"""
from __future__ import annotations

import argparse
import json
import sys

from services import chat_params, feature_gates, module_registry
from services.param_catalog import get_by_pg_key, normalize_value

# ── Каталог отчёта: существующие реестры (нового каталога НЕ создаём) ────────

EXPERIENCE_CAPABILITY = "module:experience"
LEARNING_KEY = "memory.experience_learning_enabled"


def _strict_bool(value):
    """True/False (или legacy 0/1) либо None — «записи нет/мусор»."""
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    return None


def _override_bool(root: dict, key: str):
    """Валидный bool-override чата либо None (каст по каталогу, как в коде)."""
    overrides = (root or {}).get("overrides") or {}
    if key not in overrides:
        return None
    value = overrides[key]
    spec = get_by_pg_key(key)
    if spec is not None:
        try:
            value = normalize_value(key, value)
        except Exception:
            return None
    return _strict_bool(value)


def _global_bool(globals_map: dict, key: str, default: bool = False) -> bool:
    value = globals_map.get(key)
    return default if value is None else bool(value)


def capabilities() -> list[dict]:
    """Список capability отчёта: модули реестра + домен gates (без дублей)."""
    out: list[dict] = []
    for module_id, spec in module_registry.MODULE_REGISTRY.items():
        if not spec.master_param:
            continue                    # infrastructure без master (embeddings)
        out.append({
            "id": f"module:{module_id}",
            "kind": "module",
            "module": module_id,
            "key": spec.master_param,
        })
    for feature in sorted(feature_gates.ALL_GATED_FEATURES):
        out.append({
            "id": f"gate:{feature}",
            "kind": "gate",
            "feature": feature,
        })
    return out


# ── OLD semantics (код до M2) ───────────────────────────────────────────────


def legacy_module(root: dict, key: str, globals_map: dict,
                  default: bool) -> bool:
    """Модульный мастер: chat override → глобал → дефолт (без запрета)."""
    chat = _override_bool(root, key)
    if chat is not None:
        return chat
    return _global_bool(globals_map, key, default)


def legacy_experience(root: dict, globals_map: dict) -> bool:
    """EXP-FIX-08: глобальная ось — master, OFF глушит ВСЕ чаты."""
    global_value = _global_bool(globals_map, LEARNING_KEY, True)
    if not global_value:
        return False
    chat = _override_bool(root, LEARNING_KEY)
    if chat is not None:
        return chat
    return global_value


def legacy_gate(root: dict, feature: str, globals_map: dict,
                master_default: bool = False) -> bool:
    """Гейт до M2: чат-гейт → явный flags.<f>_enabled (veto) → master →
    глобальный флаг → код-дефолт."""
    gates = (root or {}).get("gates") or {}
    if feature in gates:
        flag = _strict_bool(gates.get(feature))
        if flag is not None:
            return flag
    keys = feature_gates.FLAG_KEYS.get(feature) or ()
    if keys:
        explicit = globals_map.get(keys[0])
        if explicit is not None:
            return bool(explicit)
    alias = feature_gates.MASTER_FALLBACK_KEYS.get(feature)
    if alias:
        flag = _override_bool(root, alias)
        if flag is not None:
            return flag
        if globals_map.get(alias) is not None:
            return bool(globals_map[alias])
        return bool(master_default)
    for key in keys:
        if globals_map.get(key) is not None:
            return bool(globals_map[key])
    return bool(feature_gates.DEFAULT_BY_FEATURE.get(feature, False))


# ── NEW semantics (канонический резолвер) ───────────────────────────────────


def _gate_global(globals_map: dict, feature: str,
                 master_default: bool = False) -> bool:
    """Глобальный слой гейта так, как его передаёт feature_gates."""
    alias = feature_gates.MASTER_FALLBACK_KEYS.get(feature)
    if alias:
        if globals_map.get(alias) is not None:
            return bool(globals_map[alias])
        return bool(master_default)
    for key in feature_gates.FLAG_KEYS.get(feature) or ():
        if globals_map.get(key) is not None:
            return bool(globals_map[key])
    return bool(feature_gates.DEFAULT_BY_FEATURE.get(feature, False))


def resolve_new(cap: dict, root: dict, globals_map: dict,
                emergency: bool) -> chat_params.CapabilityState:
    """NEW: единый резолвер (тот же код, что в рантайме)."""
    if cap["kind"] == "gate":
        feature = cap["feature"]
        return chat_params.resolve_capability(
            capability=feature, key=feature, domain=chat_params.DOMAIN_GATE,
            root=root, global_value=_gate_global(globals_map, feature),
            chat_alias_key=feature_gates.COMPAT_OVERRIDE_KEYS.get(feature),
            emergency_block=emergency)
    default = module_registry.PRODUCT_DEFAULTS.get(cap["key"], True)
    return chat_params.resolve_capability(
        capability=cap["id"], key=cap["key"],
        domain=chat_params.DOMAIN_OVERRIDE, root=root,
        global_value=_global_bool(globals_map, cap["key"], default),
        emergency_block=emergency)


def legacy_effective(cap: dict, root: dict, globals_map: dict) -> bool:
    if cap["kind"] == "gate":
        return legacy_gate(root, cap["feature"], globals_map)
    if cap["id"] == EXPERIENCE_CAPABILITY:
        return legacy_experience(root, globals_map)
    default = module_registry.PRODUCT_DEFAULTS.get(cap["key"], True)
    return legacy_module(root, cap["key"], globals_map, default)


def _emergency(cap: dict, env_map: dict) -> bool:
    """Аварийная env-ось capability (перекрывает и OLD, и NEW)."""
    if cap["kind"] == "gate":
        return False
    if cap["module"] == "experience":
        return not bool(env_map.get("MCA_EXPERIENCE_LESSONS_ENABLED", True))
    gate = module_registry.ENV_GATES.get(cap["module"])
    if not gate:
        return False
    return not bool(env_map.get(gate, True))


# ── Отчёт ───────────────────────────────────────────────────────────────────


def build_report(globals_map: dict, chats: list[dict],
                 env_map: dict | None = None) -> dict:
    """Детерминированный before/after (без I/O). ``chats``:
    ``[{"chat_id": int, "overrides": {...}, "gates": {...}}]``."""
    env_map = dict(env_map or {})
    caps = capabilities()
    rows: list[dict] = []
    changed: list[dict] = []
    for chat in sorted(chats, key=lambda c: int(c["chat_id"])):
        chat_id = int(chat["chat_id"])
        root = {"overrides": dict(chat.get("overrides") or {}),
                "gates": dict(chat.get("gates") or {})}
        for cap in caps:
            emergency = _emergency(cap, env_map)
            old = legacy_effective(cap, root, globals_map)
            if emergency:
                old = False             # аварийная ось перекрывала и раньше
            new_state = resolve_new(cap, root, globals_map, emergency)
            new = bool(new_state.effective_runtime)
            rows.append({"chat_id": chat_id, "capability": cap["id"],
                         "old": old, "new": new,
                         "chat_state": new_state.chat_state,
                         "source": new_state.source,
                         "emergency_block": emergency})
            if old != new:
                changed.append({
                    "chat_id": chat_id,
                    "capability": cap["id"],
                    "old": old,
                    "new": new,
                    "chat_state": new_state.chat_state,
                    "source": new_state.source,
                })
    per_cap: dict[str, int] = {}
    for item in changed:
        per_cap[item["capability"]] = per_cap.get(item["capability"], 0) + 1
    return {
        "capabilities": [c["id"] for c in caps],
        "chats": [int(c["chat_id"]) for c in sorted(chats,
                                                    key=lambda c: int(c["chat_id"]))],
        "rows": rows,
        "changed": changed,
        "changed_pairs": len(changed),
        "changed_chats": sorted({item["chat_id"] for item in changed}),
        "changed_by_capability": dict(sorted(per_cap.items())),
    }


def render_markdown(report: dict, *, source_label: str) -> str:
    """Человеческий отчёт: поштучный список изменений (без процентов)."""
    lines = [
        "# MOD-ACL-UX-01 M2 — before/after effective state",
        "",
        f"Источник данных: {source_label}",
        "Режим: read-only (только чтение существующих строк; значения не "
        "перезаписываются).",
        "",
        f"capability: {len(report['capabilities'])} · "
        f"чатов: {len(report['chats'])} · "
        f"изменённых пар (чат × capability): {report['changed_pairs']} · "
        f"чатов с изменением поведения: {len(report['changed_chats'])}",
        "",
    ]
    if not report["changed"]:
        lines.append("Изменений effective-state нет.")
    else:
        lines.append("## Изменения по capability")
        lines.append("")
        for cap, count in report["changed_by_capability"].items():
            lines.append(f"### {cap} — {count}")
            lines.append("")
            for item in report["changed"]:
                if item["capability"] != cap:
                    continue
                lines.append(
                    f"- чат {item['chat_id']}: "
                    f"{'ON' if item['old'] else 'OFF'} → "
                    f"{'ON' if item['new'] else 'OFF'}"
                    f" (chat_state={item['chat_state']}, "
                    f"source={item['source']})")
            lines.append("")
        lines.append("## Чаты с изменением поведения (поштучно)")
        lines.append("")
        for chat_id in report["changed_chats"]:
            caps = [i["capability"] for i in report["changed"]
                    if i["chat_id"] == chat_id]
            lines.append(f"- {chat_id}: {', '.join(sorted(caps))}")
        lines.append("")
    unchanged = [c for c in report["chats"]
                 if c not in set(report["changed_chats"])]
    lines.append(f"## Без изменений — {len(unchanged)} чатов")
    lines.append("")
    if unchanged:
        lines.append(", ".join(str(c) for c in unchanged))
        lines.append("")
    return "\n".join(lines)


# ── Загрузка данных ─────────────────────────────────────────────────────────


def load_fixture(path: str) -> tuple[dict, list[dict], dict]:
    with open(path, "r", encoding="utf-8") as fh:
        data = json.load(fh)
    globals_map = dict(data.get("globals") or {})
    chats = list(data.get("chats") or [])
    env_map = dict(data.get("env") or {})
    return globals_map, chats, env_map


async def load_from_database(dsn: str | None):     # pragma: no cover - PG/DevOps
    """READ-ONLY чтение production: bot_settings + chat_profiles (SELECT).

    `PgDatabase.init()` НЕ вызывается: никакого DDL/сида/миграций."""
    import os
    from config.settings import settings
    from services import hot_config as hot
    from services.chat_lore_store import ChatLoreStore
    from services.config_cache import ConfigCache
    from services.pg_db import PgDatabase

    pg = PgDatabase(dsn=dsn or os.getenv("POSTGRES_DSN"))
    await pg.connect()
    if pg.pool is None:
        raise SystemExit("[report] PostgreSQL недоступен — read-only прогон "
                         "невозможен")
    cache = ConfigCache(pg=pg)
    await cache._load_all()                     # только SELECT
    hot.set_config_cache(cache)
    globals_map = dict(cache.get_all() or {})
    store = ChatLoreStore(pg)
    profiles = await store.list_profiles()
    chats = []
    for profile in profiles:
        root = await chat_params.get_all_chat_params(profile.chat_id, pg=pg)
        chats.append({"chat_id": int(profile.chat_id),
                      "overrides": dict((root or {}).get("overrides") or {}),
                      "gates": dict((root or {}).get("gates") or {})})
    env_map = {key: bool(getattr(settings, key, True))
               for key in list(module_registry.ENV_GATES.values())
               + ["MCA_EXPERIENCE_LESSONS_ENABLED"]}
    await pg.close()
    return globals_map, chats, env_map


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="MOD-ACL-UX-01 M2 before/after effective-state report")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--fixture", help="JSON fixture (детерминированный)")
    group.add_argument("--database", action="store_true",
                       help="read-only прогон по production PostgreSQL")
    parser.add_argument("--dsn", default=None)
    parser.add_argument("--out", default=None, help="записать отчёт в файл")
    parser.add_argument("--json", action="store_true",
                        help="машиночитаемый вывод вместо markdown")
    args = parser.parse_args(argv)

    if args.fixture:
        globals_map, chats, env_map = load_fixture(args.fixture)
        label = f"fixture={args.fixture} (детерминированный, без БД)"
    else:
        import asyncio
        globals_map, chats, env_map = asyncio.run(
            load_from_database(args.dsn))
        label = "production PostgreSQL (read-only SELECT)"

    report = build_report(globals_map, chats, env_map)
    text = (json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
            if args.json else render_markdown(report, source_label=label))
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(text + "\n")
        print(f"[report] записано: {args.out}")
    else:
        print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
