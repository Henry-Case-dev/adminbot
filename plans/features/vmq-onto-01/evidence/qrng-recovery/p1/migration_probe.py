"""QRNG P1 — миграционное доказательство v48 на копии БД (не production).

Скрипт строит временную SQLite-копию в форме «до v48» (7 легаси-партий ANU,
строка `mca_random_state`, `user_version = 47`, книги без шага 48),
применяет штатный `DatabaseService.initialize()` и печатает JSON с фактами:
PRAGMA, сохранность строк, идемпотентность, совместимость старого SQL и
backfill. Никакого доступа к production.

Запуск: `python plans/features/vmq-onto-01/evidence/qrng-recovery/p1/migration_probe.py`
"""
import asyncio
import hashlib
import json
import sqlite3
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[6]))

from services import mca_random_source as mrs          # noqa: E402
from services.database import DatabaseService         # noqa: E402

LEGACY_KEY = "anu-prod-shape-key-Lz5l"


async def _count(db, sql: str, params=()) -> int:
    cur = await db.db.execute(sql, params)
    row = await cur.fetchone()
    return int(row[0])


def _legacy_rows() -> list:
    rows = []
    for index in range(7):
        values = json_values(index)
        rows.append({
            "batch_id": hashlib.sha256(f"legacy-{index}".encode()).hexdigest()[:32],
            "provider": mrs.PROVIDER_ANU,
            "data_type": "uint16",
            "length": len(values),
            "values_json": json.dumps(values, separators=(",", ":")),
            "reserved_upto": index * 3,
            "consumed_upto": index * 3,
            "source": "quantum",
            "created_at": 1770000000 + index,
        })
    return rows


def json_values(index: int) -> list:
    return [((index * 97 + pos) % 65536) for pos in range(64)]


async def main() -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="qrng_p1_migration_"))
    path = str(tmp / "pre_v48_copy.db")
    out: dict = {"db": path}

    # 1) Форма «до v48»: полная схема, затем откат random-store к v47.
    db = DatabaseService(path)
    await db.initialize()
    await db.close()
    legacy = _legacy_rows()
    raw = sqlite3.connect(path)
    raw.execute("ALTER TABLE mca_random_batches DROP COLUMN config_fingerprint")
    raw.execute("ALTER TABLE mca_random_batches DROP COLUMN external_ref")
    raw.execute("PRAGMA user_version = 47")
    raw.execute("DELETE FROM schema_migrations WHERE version = 48")
    for row in legacy:
        raw.execute(
            "INSERT INTO mca_random_batches (batch_id, provider, data_type, "
            "length, values_json, reserved_upto, consumed_upto, source, "
            "created_at) VALUES (?,?,?,?,?,?,?,?,?)",
            (row["batch_id"], row["provider"], row["data_type"], row["length"],
             row["values_json"], row["reserved_upto"], row["consumed_upto"],
             row["source"], row["created_at"]))
    raw.execute(
        "INSERT OR REPLACE INTO mca_random_state (scope, key_fingerprint, "
        "activation_batch_id, activated_at, last_fallback_reason, "
        "last_fallback_at, updated_at) VALUES ('anu', ?, ?, ?, NULL, NULL, ?)",
        (mrs.key_fingerprint(LEGACY_KEY), legacy[0]["batch_id"],
         1770000100, 1770000100))
    raw.commit()
    out["before"] = {
        "user_version": raw.execute("PRAGMA user_version").fetchone()[0],
        "columns": [r[1] for r in raw.execute(
            "PRAGMA table_info(mca_random_batches)")],
        "batch_rows": raw.execute(
            "SELECT COUNT(*) FROM mca_random_batches").fetchone()[0],
        "state_rows": raw.execute(
            "SELECT COUNT(*) FROM mca_random_state").fetchone()[0],
        "book_has_48": raw.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version = 48"
        ).fetchone()[0],
    }
    raw.close()

    # 2) Миграция штатным runner'ом (только шаг 48 > current).
    started = time.monotonic()
    db = DatabaseService(path)
    await db.initialize()
    out["migration_seconds"] = round(time.monotonic() - started, 3)
    try:
        cur = await db.db.execute("PRAGMA user_version")
        columns = {r["name"]: dict(r) for r in await (await db.db.execute(
            "PRAGMA table_info(mca_random_batches)")).fetchall()}
        out["after"] = {
            "user_version": int((await cur.fetchone())[0]),
            "has_config_fingerprint": "config_fingerprint" in columns,
            "has_external_ref": "external_ref" in columns,
            "config_fingerprint_nullable": (
                columns.get("config_fingerprint", {}).get("notnull") == 0),
            "book_48_rows": await _count(
                db, "SELECT COUNT(*) FROM schema_migrations WHERE version = 48"),
        }
        cur = await db.db.execute(
            "SELECT batch_id, provider, length, reserved_upto, consumed_upto, "
            "source, created_at, config_fingerprint, external_ref "
            "FROM mca_random_batches ORDER BY created_at")
        rows = [dict(r) for r in await cur.fetchall()]
        out["rows"] = {
            "count": len(rows),
            "providers": sorted({r["provider"] for r in rows}),
            "all_fingerprint_null": all(r["config_fingerprint"] is None
                                        for r in rows),
            "all_external_ref_null": all(r["external_ref"] is None
                                         for r in rows),
            "identical_to_before": all(
                (r["batch_id"], r["provider"], r["length"], r["reserved_upto"],
                 r["consumed_upto"], r["source"], r["created_at"])
                == (legacy[i]["batch_id"], legacy[i]["provider"],
                    legacy[i]["length"], legacy[i]["reserved_upto"],
                    legacy[i]["consumed_upto"], legacy[i]["source"],
                    legacy[i]["created_at"])
                for i, r in enumerate(rows)),
        }

        # 3) Старый код (2.58.213) не читает новые колонки: те же SQL живы.
        cur = await db.db.execute(
            "SELECT batch_id, provider, data_type, values_json, "
            "reserved_upto, length FROM mca_random_batches "
            "WHERE reserved_upto < length ORDER BY created_at, batch_id LIMIT 1")
        old_select = await cur.fetchone()
        out["old_code"] = {
            "select_ok": old_select is not None,
            "legacy_batch_consumable": old_select is not None and
            int(old_select["reserved_upto"]) < int(old_select["length"]),
            "reserve_remaining_unfiltered": await _count(
                db, "SELECT COALESCE(SUM(length - reserved_upto), 0) "
                    "FROM mca_random_batches WHERE reserved_upto < length"),
        }

        # 4) Идемпотентность: повторный initialize и повтор шага.
        await db.close()
        db = DatabaseService(path)
        await db.initialize()
        out["idempotent"] = {
            "batch_rows": await _count(
                db, "SELECT COUNT(*) FROM mca_random_batches"),
            "book_48_rows": await _count(
                db, "SELECT COUNT(*) FROM schema_migrations WHERE version = 48"),
        }
        await db._migrate_random_batch_provenance_v48()
        out["idempotent"]["book_48_rows_after_manual_rerun"] = await _count(
            db, "SELECT COUNT(*) FROM schema_migrations WHERE version = 48")

        # 5) Backfill: только NULL-партии ANU при подтверждённом том же ключе.
        svc = mrs.RandomSourceService(db, auto_refill=False)
        svc._resolve_key = lambda: LEGACY_KEY
        fp = mrs.key_fingerprint(LEGACY_KEY)
        out["backfill"] = {
            "first_run": await svc.sync_batch_provenance(),
            "second_run": await svc.sync_batch_provenance(),
            "fingerprinted_rows": await _count(
                db, "SELECT COUNT(*) FROM mca_random_batches "
                    "WHERE config_fingerprint = ?", (fp,)),
            "reserve_scoped": await svc._store.reserve_remaining(
                config_fingerprint=fp),
            "reserve_other_key": await svc._store.reserve_remaining(
                config_fingerprint=mrs.key_fingerprint("another-key")),
            "provider_reserve": await svc._store.provider_reserve(),
        }
        svc._resolve_key = lambda: "another-key"
        out["backfill"]["wrong_key_run"] = await svc.sync_batch_provenance()
    finally:
        await db.close()
    return out


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), ensure_ascii=False, indent=2))
