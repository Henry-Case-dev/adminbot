"""QRNG P1 F2/F3/F4 — поведенческий RED/GREEN-пробник.

Проверяет публичную проекцию `/api/status` (`StatusService.random_source_snapshot`)
и фактическое расходование партий после ротации/удаления ключа. Совместим с
базой `438046d6` и с исправленной веткой (используются только существующие
на обеих сторонах API).

Запуск: `python plans/features/vmq-onto-01/evidence/qrng-recovery/p1/probe_f2f3f4.py`
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[6]))

from services import mca_random_source as mrs          # noqa: E402
from services.database import DatabaseService         # noqa: E402
from services.status_service import StatusService     # noqa: E402


class FakeClock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def ok_uint16(length: int):
    return (200, {},
            '{"success": true, "type": "uint16", "length": %d, "data": %s}'
            % (length, list(range(length))))


def _http(responses):
    async def http_get(url, headers, params, timeout):
        status, hdrs, text = responses.pop(0)
        return mrs._HttpResponse(status=status, headers=hdrs, text=text)

    return http_get


def _fingerprint_keys(payload, prefix="") -> list:
    found = []
    if isinstance(payload, dict):
        for key, value in payload.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if "fingerprint" in str(key).lower():
                found.append(path)
            found.extend(_fingerprint_keys(value, path))
    elif isinstance(payload, list):
        for index, value in enumerate(payload):
            found.extend(_fingerprint_keys(value, f"{prefix}[{index}]"))
    return found


async def _rows(db) -> list:
    cur = await db.db.execute(
        "SELECT reserved_upto, length, config_fingerprint "
        "FROM mca_random_batches ORDER BY created_at, batch_id")
    return [dict(r) for r in await cur.fetchall()]


async def main() -> dict:
    tmp = Path(tempfile.mkdtemp(prefix="qrng_f2f3f4_"))
    cfg: dict = {mrs.SETTING_BATCH_LENGTH: 8, mrs.SETTING_KEY: "anu-key-A"}
    mrs._hot_setting = lambda key, default: cfg.get(key, default)

    async def _mem(key, chat_id, default):
        return default

    mrs._read_memory_setting = _mem
    db = DatabaseService(str(tmp / "probe.db"))
    await db.initialize()
    out: dict = {"module": mrs.__file__}
    try:
        client = mrs.AnuClient(http_get=_http([ok_uint16(8)]),
                               min_interval=0.0, clock=FakeClock())
        svc = mrs.RandomSourceService(db, client=client, auto_refill=False)
        assert (await svc.activate())["activated"] is True
        state = await svc._read_state() or {}
        state_fp = str(state.get("key_fingerprint") or "")
        mrs._service = svc

        # F2: публичная проекция /api/status не должна содержать fingerprint.
        snapshot = await StatusService().random_source_snapshot(
            chat_id=None, is_global_admin=True)
        blob = json.dumps(snapshot, ensure_ascii=False, default=str)
        out["f2"] = {
            "state_fingerprint_len": len(state_fp),
            "fingerprint_keys_in_status": _fingerprint_keys(snapshot),
            "state_fingerprint_value_in_status": bool(state_fp) and state_fp in blob,
            "last_batch_keys": sorted(
                (snapshot.get("last_batch") or {}).keys()),
        }

        # F3: после A→B остаток должен быть 0 (quarantined), не 7.
        cfg[mrs.SETTING_KEY] = "anu-key-B"
        rotated = await StatusService().random_source_snapshot(
            chat_id=None, is_global_admin=True)
        out["f3"] = {
            "effective": rotated.get("effective_source"),
            "provider_reserve": rotated.get("provider_reserve"),
            "provider_quarantined": rotated.get("provider_quarantined"),
            "last_batch_config_matches": (
                rotated.get("last_batch") or {}).get("config_matches"),
        }

        # F4: удаление ключа не делает партии A расходуемыми.
        svc._resolve_key = lambda: ""
        before = await _rows(db)
        draw = await svc.draw_index(5, chat_id=1, purpose="probe")
        after = await _rows(db)
        out["f4"] = {
            "draw_source": draw.source,
            "draw_deferred": draw.deferred,
            "reserved_before": [r["reserved_upto"] for r in before],
            "reserved_after": [r["reserved_upto"] for r in after],
            "fingerprints": [r["config_fingerprint"] for r in after],
        }
    finally:
        await db.close()
    return out


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), ensure_ascii=False, indent=2))
