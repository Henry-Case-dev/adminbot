"""QRNG P3 — поведенческий RED/GREEN-пробник селектора (без сети).

Запуск из корня worktree:
`python plans/features/vmq-onto-01/evidence/qrng-recovery/p3/red_probe.py`

Скрипт использует ТОЛЬКО публичные/существующие точки (`RandomStore`,
`RandomSourceService`, каталог) плюс `getattr` для P3-символов, поэтому
исполняется и на базе `84abc2e5` (старое поведение), и на кандидате.
Печатает один JSON: что именно отсутствует/игнорируется на базе и что
работает на кандидате.
"""
import asyncio
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT))

from services import mca_random_source as mrs  # noqa: E402
from services import param_catalog as pc  # noqa: E402
from services.database import DatabaseService  # noqa: E402

PRIMARY = "random.primary_provider"
ORDER = "random.fallback_order"
FB_ENABLED = "random.fallback_enabled"


async def _run() -> dict:
    cfg: dict = {mrs.SETTING_BATCH_LENGTH: 8}
    mem: dict = {}

    mrs._hot_setting = lambda key, default: cfg.get(key, default)  # type: ignore

    async def _mem(key, chat_id, default):
        return mem.get(key, default)

    mrs._read_memory_setting = _mem  # type: ignore

    tmp = Path(tempfile.mkdtemp(prefix="qrng_p3_probe_"))
    db = DatabaseService(str(tmp / "probe.db"))
    await db.initialize()
    out: dict = {"python": sys.version.split()[0]}
    try:
        out["has_resolve_selection"] = hasattr(mrs.RandomSourceService,
                                              "resolve_selection")
        out["has_primary_setting"] = hasattr(mrs, "SETTING_PRIMARY_PROVIDER")
        out["catalog_has_primary"] = pc.get_by_pg_key(PRIMARY) is not None
        out["catalog_has_order"] = pc.get_by_pg_key(ORDER) is not None
        out["catalog_has_fb_enabled"] = pc.get_by_pg_key(FB_ENABLED) is not None
        spec = pc.get_by_pg_key("keys.random_quantum_provider")
        out["provider_info_hidden"] = bool(spec.hidden) if spec else None

        store = mrs.RandomStore(db)
        await store.insert_batch(mrs.AnuBatch(
            values=list(range(10)), data_type="uint16", length=10,
            provider=mrs.PROVIDER_ID_ANU), created_at=1000)
        await store.insert_batch(mrs.AnuBatch(
            values=[7, 8, 9, 10], data_type="uint8", length=4,
            provider=mrs.PROVIDER_ID_LFDR), created_at=2000)

        svc = mrs.RandomSourceService(db, auto_refill=False)
        cfg["random.primary_provider"] = "lfdr"
        cfg["random.fallback_enabled"] = True
        cfg["random.fallback_order"] = ["anu"]
        draw = await svc.draw_index(2, chat_id=1, purpose="p")
        out["draw_provider_on_selected_lfdr"] = draw.provider_id
        snap = await svc.status_snapshot(chat_id=1)
        out["status_has_selector"] = "resolved_primary" in snap
        out["status_resolved_primary"] = snap.get("resolved_primary")
        out["status_primary_setting_raw"] = snap.get("primary_setting_raw")
        out["status_effective_provider"] = snap.get("effective_provider")
        out["retired_state_supported"] = (
            getattr(mrs, "PRIMARY_SETTING_REQUIRES_RESOLUTION", None)
            is not None)
        if hasattr(svc, "resolve_selection"):
            cfg["random.primary_provider"] = "lizaonair"
            res = await svc.resolve_selection(1)
            out["retired"] = {
                "raw": res.primary_setting_raw,
                "state": res.primary_setting_state,
                "order": list(res.effective_order),
                "resolved_primary": res.resolved_primary,
            }
    finally:
        await db.close()
    return out


if __name__ == "__main__":
    print(json.dumps(asyncio.run(_run()), ensure_ascii=False, indent=2))
