"""Раунд 10.10 (ADR-1010-1) — выключить тяжёлые модули (сон/ностальгия/
саммаризация) для ВСЕХ активных ЛС + безопасный откат.

Хранилище — PG `chat_profiles.chat_params` (JSONB); ноль новых PG-DDL.
Пишем ТОЛЬКО через `chat_params.set_chat_params` (транзакция + история +
NOTIFY). Ключи — единый источник `chat_params._DM_DISABLED_*`.

Поведение:
  * по умолчанию **dry-run** (ничего не пишем);
  * `--apply` — снапшот overrides/gates ДО записи (abort при ошибке
    снапшота), затем запись;
  * `--chat-id <id>` (повторяемый) — подмножество (staged);
  * `--snapshot-out <path>` — путь снапшота;
  * `--restore <path>` — вернуть overrides/gates из снапшота.

Идемпотентность: повторный `--dry-run` после `--apply` = 0 изменений;
пустой патч (уже false) = no-op. Только stdout, без секретов.
"""
import argparse
import asyncio
import datetime
import json
import os
import sys
from pathlib import Path

# Standalone-запуск (`python scripts/disable_dm_heavy_modules.py`): Python
# кладёт в sys.path каталог скрипта, а не корень репозитория — добавляем
# корень, чтобы импортировался пакет `services` (как в seed_chat_lore.py).
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from services import chat_params
from services.chat_params import _DM_DISABLED_GATES, _DM_DISABLED_OVERRIDES
from services.pg_db import PgDatabase

# Прямой SELECT: `chat_lore_store.list_profiles` исключает ЛС (chat_id < 0);
# standalone-скрипту нужны именно положительные активные чаты.
DM_PROFILES_SQL = (
    "SELECT chat_id, chat_params, gates_opt_in FROM chat_profiles "
    "WHERE chat_id > 0 AND is_active = TRUE ORDER BY chat_id"
)

_SNAPSHOT_DIR = "var"


def _utc_stamp() -> str:
    return datetime.datetime.now(
        datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def default_snapshot_path() -> str:
    return os.path.join(_SNAPSHOT_DIR,
                        f"dm_modules_off_snapshot_{_utc_stamp()}.json")


def build_dm_patch(overrides, gates) -> tuple[dict, dict]:
    """Патч (overrides, gates) для чата: только ключи, где текущее значение
    НЕ False. Уже false/записанный false → no-op (идемпотентность).
    Изолированная чистая функция — тестируется напрямую."""
    cur_o = dict(overrides or {})
    cur_g = dict(gates or {})
    patch_o = {k: False for k in _DM_DISABLED_OVERRIDES
               if cur_o.get(k) is not False}
    patch_g = {k: False for k in _DM_DISABLED_GATES
               if cur_g.get(k) is not False}
    return patch_o, patch_g


def select_scope(rows, chat_ids=None) -> list[dict]:
    """Строки выбранного scope: при `chat_ids` — только эти chat_id
    (staged). Соответствие scope и отчёта (noop/total/counts) — см. run()."""
    if not chat_ids:
        return list(rows or [])
    wanted = set(int(c) for c in chat_ids)
    return [r for r in (rows or []) if int(r["chat_id"]) in wanted]


def collect_plan(rows, chat_ids=None) -> list[dict]:
    """План изменений по строкам профилей. Пустой патч → чат пропускается
    (no-op). `chat_ids` (если задан) — только эти чаты (staged)."""
    plan: list[dict] = []
    for row in select_scope(rows, chat_ids):
        chat_id = int(row["chat_id"])
        root = chat_params._load_chat_params(row.get("chat_params"))
        patch_o, patch_g = build_dm_patch(
            root.get("overrides"), root.get("gates"))
        if not patch_o and not patch_g:
            continue
        plan.append({
            "chat_id": chat_id,
            "root": root,
            "patch_overrides": patch_o,
            "patch_gates": patch_g,
        })
    return plan


def build_snapshot(plan) -> dict:
    """Снапшот overrides/gates/meta (без секретов) для rollback. `meta`
    сохраняем, чтобы `--restore` возвращал и прежний `meta.note`, а не
    терял его (info-находка Scanner)."""
    return {
        "version": 1,
        "created_at": datetime.datetime.now(
            datetime.timezone.utc).isoformat(),
        "chats": [
            {
                "chat_id": int(e["chat_id"]),
                "overrides": dict(e["root"].get("overrides") or {}),
                "gates": dict(e["root"].get("gates") or {}),
                "meta": dict(e["root"].get("meta") or {}),
            }
            for e in plan
        ],
    }


def write_snapshot(path: str, plan) -> None:
    """Запись снапшота (best-effort 0o600). Ошибка → исключение (abort)."""
    target = Path(path)
    if target.parent and str(target.parent):
        target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(build_snapshot(plan), ensure_ascii=False, indent=2),
        encoding="utf-8")
    try:
        os.chmod(target, 0o600)
    except OSError:
        pass


async def fetch_dm_profiles(pg) -> list[dict]:
    """Активные ЛС: chat_id > 0 AND is_active = TRUE (raw SQL через пул)."""
    pool = getattr(pg, "pool", None) if pg is not None else None
    if pool is None:
        return []
    async with pool.acquire() as conn:
        rows = await conn.fetch(DM_PROFILES_SQL)
    return [dict(r) for r in rows]


async def apply_plan(pg, plan) -> dict:
    """Запись merged overrides/gates через set_chat_params (namespace
    заменяется целиком — передаём полные словари)."""
    changed = 0
    errors: list[int] = []
    for entry in plan:
        root = entry["root"]
        merged_o = {**dict(root.get("overrides") or {}),
                    **entry["patch_overrides"]}
        merged_g = {**dict(root.get("gates") or {}),
                    **entry["patch_gates"]}
        merged_meta = {**dict(root.get("meta") or {}),
                       "note": "dm heavy modules off"}
        try:
            await chat_params.set_chat_params(
                entry["chat_id"],
                {"overrides": merged_o, "gates": merged_g, "meta": merged_meta},
                changed_by=None, pg=pg, history_field="chat_params")
        except Exception as exc:  # noqa: BLE001 — best-effort по чату
            errors.append(entry["chat_id"])
            print(f"[dm_off] chat={entry['chat_id']} FAILED: {exc}")
            continue
        changed += 1
        print(f"[dm_off] chat={entry['chat_id']} overrides="
              f"{entry['patch_overrides']} gates={entry['patch_gates']}")
    return {"changed": changed, "errors": errors}


async def restore_from_snapshot(pg, snapshot_path: str) -> dict:
    """Вернуть overrides/gates (+ `meta`, если он есть в снапшоте) —
    идемпотентно.

    meta: новые снапшоты его содержат → возвращаем faithfully (прежний
    `meta.note` не теряется). Legacy-снапшоты без ключа `meta` — НЕ
    трогаем namespace вовсе, чтобы не затирать текущий meta пустым.

    LOW-RESTORE: возвращаем {restored, total, errors} — восстановление с
    частичным сбоем не должно выглядеть успехом (per-chat исключения тут
    только логируются, решение об exit-коде принимает `run`)."""
    data = json.loads(Path(snapshot_path).read_text(encoding="utf-8"))
    chats = data.get("chats") or []
    restored = 0
    errors: list[int] = []
    for entry in chats:
        chat_id = int(entry["chat_id"])
        patch = {
            "overrides": dict(entry.get("overrides") or {}),
            "gates": dict(entry.get("gates") or {}),
        }
        if "meta" in entry:
            patch["meta"] = dict(entry.get("meta") or {})
        try:
            await chat_params.set_chat_params(
                chat_id, patch,
                changed_by=None, pg=pg, history_field="chat_params")
            restored += 1
        except Exception as exc:  # noqa: BLE001
            errors.append(chat_id)
            print(f"[dm_off] restore chat={chat_id} FAILED: {exc}")
    return {"restored": restored, "total": len(chats), "errors": errors}


def parse_args(argv=None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Выключить сон/ностальгию/саммаризацию для активных ЛС")
    parser.add_argument("--apply", action="store_true",
                        help="записать изменения (по умолчанию dry-run)")
    parser.add_argument("--dry-run", action="store_true",
                        help="явный dry-run (по умолчанию; перебивает --apply)")
    parser.add_argument("--chat-id", action="append", type=int, default=None,
                        help="только этот chat_id (можно повторять; staged)")
    parser.add_argument("--snapshot-out", default=None,
                        help="путь снапшота перед apply")
    parser.add_argument("--restore", default=None,
                        help="вернуть overrides/gates из снапшота")
    return parser.parse_args(argv)


async def run(argv=None, pg=None) -> int:
    args = parse_args(argv)
    own_pg = pg is None
    if own_pg:
        pg = PgDatabase(dsn=os.getenv("POSTGRES_DSN"))
        await pg.connect()
    try:
        if args.restore:
            res = await restore_from_snapshot(pg, args.restore)
            print(f"[dm_off] restore done: "
                  f"restored={res['restored']}/{res['total']} "
                  f"errors={len(res['errors'])}")
            # LOW-RESTORE: частичный сбой (или restored < total) → exit 1.
            failed = bool(res["errors"]) or res["restored"] != res["total"]
            return 1 if failed else 0

        rows = await fetch_dm_profiles(pg)
        # Scope-отчёт: noop/total считаем по ВЫБРАННОМУ scope (--chat-id),
        # иначе staged-прогон показывал бы цифры по всем ЛС.
        scoped = select_scope(rows, args.chat_id)
        total = len(scoped)
        plan = collect_plan(scoped)
        apply = args.apply and not args.dry_run
        if not apply:
            for entry in plan:
                print(f"[dry-run] chat={entry['chat_id']} overrides="
                      f"{entry['patch_overrides']} gates={entry['patch_gates']}")
            print(f"[dm_off] планируется {len(plan)} изменений из {total} ЛС")
            return 0

        snapshot_path = args.snapshot_out or default_snapshot_path()
        if plan:
            try:
                write_snapshot(snapshot_path, plan)
            except Exception as exc:  # noqa: BLE001 — abort без записи
                print(f"[dm_off] snapshot FAILED — abort: {exc}")
                return 1
            print(f"[dm_off] snapshot: {snapshot_path} ({len(plan)} ЛС)")
        res = await apply_plan(pg, plan)
        print(f"[dm_off] changed={res['changed']} noop={total - len(plan)} "
              f"total={total} errors={len(res['errors'])}")
        # LOW-3: частичный сбой не должен выглядеть успехом.
        return 1 if res["errors"] else 0
    finally:
        if own_pg:
            await pg.close()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()) or 0)
