"""Раунд 10 (F-9 T-885, C2) — бэкфил gates.permsoc для существующих чатов.

Правило (Q3, детерминированное; запуск @DevOps при деплое, до рестарта):
  master ON ⟺ chat_id == -1002661910336
           OR chat_profiles.relations_enabled == true
           OR manual_lore <> '' OR auto_lore <> ''
           OR EXISTS (SELECT 1 FROM chat_admins WHERE chat_id = ...)
  master OFF — иначе.
Повторный запуск — no-op (существующее значение gates.permsoc НЕ
перезаписывается); пишем ТОЛЬКО если gates.permsoc отсутствует. Вывод —
только stdout (без значений ключей/секретов).
"""
import asyncio
import sys

from services import chat_params
from services.chat_lore_store import ChatLoreStore
from services.pg_db import PgDatabase

YARY_CHAT_ID = -1002661910336


async def main() -> int:
    from config.settings import settings
    pg = PgDatabase(dsn=settings.POSTGRES_DSN)
    await pg.connect()
    if pg.pool is None:
        print("[backfill_permsoc] PostgreSQL недоступен — skip")
        return 1
    store = ChatLoreStore(pg)
    profiles = await store.list_profiles()
    changed = 0
    for profile in profiles:
        chat_id = profile.chat_id
        root = await chat_params.get_all_chat_params(chat_id)
        gates = root.get("gates") or {}
        if "permsoc" in gates:
            continue                      # существующее значение — no-op
        relations_enabled = bool(profile.relations_enabled)
        has_lore = bool((profile.manual_lore or "").strip()
                        or (profile.auto_lore or "").strip())
        admins = await store.list_chat_admins(chat_id)
        master_on = (chat_id == YARY_CHAT_ID or relations_enabled
                     or has_lore or bool(admins))
        try:
            await chat_params.set_chat_params(
                chat_id,
                {"gates": {**gates, "permsoc": master_on},
                 "meta": {"updated_by": None,
                          "note": "backfill permsoc (deploy)"}},
                changed_by=None, pg=pg, history_field="gates")
        except Exception as exc:
            print(f"[backfill_permsoc] chat={chat_id} FAILED: {exc}")
            continue
        print(f"[backfill_permsoc] chat={chat_id} gates.permsoc="
              f"{master_on}")
        changed += 1
    await pg.close()
    print(f"[backfill_permsoc] done: {changed} чатов записано "
          f"(из {len(profiles)})")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()) or 0)
