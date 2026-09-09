"""Раунд 10.4 (B-4) — идемпотентный бэкфил per-chat флага для
chat_id=-1002661910336: `flags.chat_context_budgets_enabled` → `false`
(экономия токенов: у чата нет BYOK-ключа, глобальный ключ 25 req/сутки).

Правила (спека B-4):
  * ensure_scope_profile(chat_id, dm=False) — профиль создаётся при первом
    запуске (иначе set_chat_params дал бы мусорный 409 «профиля нет»);
  * запись ТОЛЬКО при отсутствии ключа в overrides (не перезаписывает
    существующий выбор админа — повторный прогон no-op);
  * expected_updated_at=None — последняя запись побеждает (идемпотентность);
  * канон write-path: set_chat_params (NOTIFY/кэш-инвалидация/история).

Запуск: python scripts/backfill_104_chat_flags.py [--dry-run]
"""
import asyncio
import sys

TARGET_CHAT_ID = -1002661910336
FLAG_KEY = "flags.chat_context_budgets_enabled"


async def _run(dry_run: bool) -> int:
    from services import chat_params
    from services import hot_config as hot

    cache = hot.get_config_cache()
    if cache is None or getattr(cache, "pg", None) is None:
        print("[backfill_104] ConfigCache/PG недоступен — выход")
        return 1
    pg = cache.pg

    await chat_params.ensure_scope_profile(TARGET_CHAT_ID, dm=False, pg=pg)
    root = await chat_params.get_all_chat_params(TARGET_CHAT_ID)
    overrides = dict(root.get("overrides") or {})
    if FLAG_KEY in overrides:
        print(f"[backfill_104] skip: {FLAG_KEY} уже в overrides = "
              f"{overrides[FLAG_KEY]!r} (no-op)")
        return 0
    print(f"[backfill_104] write: {FLAG_KEY} = false")
    if dry_run:
        print("[backfill_104] dry-run — запись пропущена")
        return 0
    meta = dict(root.get("meta") or {})
    meta["note"] = "backfill_104: budgets off (нет BYOK, глобальный лимит)"
    new_overrides = dict(overrides)
    new_overrides[FLAG_KEY] = False
    await chat_params.set_chat_params(
        TARGET_CHAT_ID, {"overrides": new_overrides, "meta": meta},
        changed_by=None, pg=pg)
    print("[backfill_104] done: flag off, NOTIFY/история эмитированы")
    return 0


def main() -> int:
    dry_run = "--dry-run" in sys.argv
    return asyncio.run(_run(dry_run))


if __name__ == "__main__":
    sys.exit(main())
