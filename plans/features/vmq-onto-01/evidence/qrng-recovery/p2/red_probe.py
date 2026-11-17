"""QRNG P2 — поведенческий RED/GREEN-пробник адаптера LfDR.

Запуск: `python plans/features/vmq-onto-01/evidence/qrng-recovery/p2/red_probe.py`
(скрипт копируется в worktree проверяемой ревизии; пишет JSON одним объектом).
Проверяет только публичное поведение: наличие адаптера/guard'а, точку входа
реестра, фактический запрос и коды guard'а. Сети не касается (`http_get`
инъецируется).
"""
import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[6]))

from services import mca_random_source as mrs          # noqa: E402


def _spec_info() -> dict | None:
    registry = getattr(mrs, "PROVIDERS", None)
    if not isinstance(registry, dict) or "lfdr" not in registry:
        return None
    spec = registry["lfdr"]
    return {
        "id": spec.id,
        "entropy_class": spec.entropy_class,
        "requires_key": bool(spec.requires_key),
        "key_setting": spec.key_setting,
        "fetch": getattr(getattr(spec, "fetch", None), "__name__", None),
        "check": getattr(getattr(spec, "check", None), "__name__", None),
    }


async def _fetch_probe() -> dict:
    calls: list = []

    async def http_get(url, headers, params, timeout):
        calls.append({"url": url, "headers": dict(headers),
                      "params": dict(params)})
        return mrs._HttpResponse(
            status=200, headers={},
            text=json.dumps({"length": 2, "qrn": "5ef1"}))

    batch = await mrs.lfdr_fetch(length=2, http_get=http_get)
    return {"values": batch.values, "provider": batch.provider,
            "data_type": batch.data_type, "calls": calls}


def _guard_probe() -> dict:
    cases = ("http://lfdr.de/qrng_api/qrng",
             "https://lfdr.de/qrng",
             "https://user@lfdr.de/qrng_api/qrng",
             "https://lfdr.de:8443/qrng_api/qrng",
             "https://lfdr.de/qrng_api/qrng?length=1")
    out: dict = {}
    for url in cases:
        try:
            mrs.validate_lfdr_endpoint(url)
            out[url] = "ACCEPTED"
        except mrs.AnuError as exc:
            out[url] = exc.code
    return out


def main() -> dict:
    out: dict = {"module": mrs.__file__}
    out["has_lfdr_client"] = hasattr(mrs, "LfdrClient")
    out["has_validate_lfdr_endpoint"] = hasattr(mrs, "validate_lfdr_endpoint")
    out["has_lfdr_fetch_entry"] = hasattr(mrs, "lfdr_fetch")
    out["registry_lfdr"] = _spec_info()
    if out["has_lfdr_client"] and out["has_lfdr_fetch_entry"]:
        out["fetch"] = asyncio.run(_fetch_probe())
    if out["has_validate_lfdr_endpoint"]:
        out["guard"] = _guard_probe()
    return out


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2))
