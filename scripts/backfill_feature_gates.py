"""Раунд 10 (F-10 T-893, C1) — бэкфил гейтов тяжёлых фич для существующих чатов.

Правило (Q3; запуск @DevOps при деплое, после миграции DDL, до живых тиков):
  gates[dream|nostalgia|lore_auto] = текущее ГЛОБАЛЬНОЕ значение
  (резолв по цепочке FLAG_KEYS: hot.get flags.<feature>_enabled →
  memory.<feature>_enabled → DEFAULT_BY_FEATURE — фикс S3: FLAG_BY_FEATURE
  не существует; единый _global_flag_value из services/feature_gates.py)
  gates_opt_in = true, если хоть один из трёх = ON; иначе false
Запись — ТОЛЬКО если gate отсутствует (существующие значения НЕ затираем —
идемпотентность: повторный запуск = no-op). Чат без профиля — скип.
Только stdout (без секретов).
"""
import asyncio
import os
import sys

from services import chat_params, feature_gates
from services.chat_lore_store import ChatLoreStore
from services.pg_db import PgDatabase


def build_gate_patch(gates: dict, values: dict[str, bool]) -> dict[str, bool]:
    """Патч gates для чата: только ключи, которых ЕЩЁ нет в `gates`
    (существующие не затираем — идемпотентность F-10 §4). Пустой словарь =
    no-op. Изолированная функция — тестируется напрямую."""
    current = dict(gates or {})
    patch: dict[str, bool] = {}
    for feature, value in sorted(values.items()):
        if feature in current:
            continue
        patch[feature] = bool(value)
    return patch


async def global_flag_values(pg=None) -> dict[str, bool]:
    """Эффективные глобальные значения тяжёлых фич (F-10 §2-резолв, слой 2:
    явные chat-гейты отсутствуют → глобальный флаг / дефолт)."""
    out: dict[str, bool] = {}
    for feature in sorted(feature_gates.HEAVY_FEATURES):
        try:
            out[feature] = bool(feature_gates._global_flag_value(feature))
        except Exception:
            out[feature] = bool(
                feature_gates.DEFAULT_BY_FEATURE.get(feature, False))
    return out


async def main() -> int:
    pg = PgDatabase(dsn=os.getenv("POSTGRES_DSN"))
    await pg.connect()
    if pg.pool is None:
        print("[backfill_gates] PostgreSQL недоступен — skip")
        return 1
    store = ChatLoreStore(pg)
    profiles = await store.list_profiles()
    values = await global_flag_values(pg)
    changed_list = []
    opt_in_chats = 0
    for profile in profiles:
        chat_id = profile.chat_id
        root = await chat_params.get_all_chat_params(chat_id)
        patch = build_gate_patch(dict(root.get("gates") or {}), values)
        if not patch:
            print(f"[backfill_gates] chat={chat_id} нет изменений (гейты "
                  f"записаны)")
            continue
        try:
            await chat_params.set_chat_params(
                chat_id, {"gates": {**(root.get("gates") or {}), **patch},
                          "meta": {"updated_by": None,
                                   "note": "backfill feature gates"}},
                changed_by=None, pg=pg, history_field="gates")
        except Exception as exc:
            print(f"[backfill_gates] chat={chat_id} FAILED: {exc}")
            continue
        any_on = any(patch[f] for f in patch)
        if any_on:
            try:
                await chat_params.set_gates_opt_in(chat_id, pg=pg)
                opt_in_chats += 1
            except Exception as exc:
                print(f"[backfill_gates] chat={chat_id} opt_in FAILED: {exc}")
        changed_list.append(chat_id)
        print(f"[backfill_gates] chat={chat_id} gates={patch} "
              f"opt_in={any_on}")
    await pg.close()
    print(f"[backfill_gates] done: записано {len(changed_list)} чатов "
          f"(opt_in={opt_in_chats}) из {len(profiles)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
