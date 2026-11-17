"""QRNG P2 — живой публичный probe LfDR (без ключа, ровно один малый GET).

Запуск из корня worktree:
`python plans/features/vmq-onto-01/evidence/qrng-recovery/p2/live_probe.py`
Использует боевой путь адаптера (`_default_http_get`, TLS-верификация,
`follow_redirects=False`). Пишет JSON одним объектом в stdout; ключ не нужен и
не отправляется. Если провайдер недоступен, фиксируется честная ошибка.
"""
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[6]))

from services import mca_random_source as mrs          # noqa: E402

PROBE_LENGTH = 2


async def main() -> dict:
    client = mrs.LfdrClient(min_interval=0.0)
    started = time.perf_counter()
    out: dict = {
        "endpoint": mrs.LFDR_ENDPOINT,
        "method": "GET",
        "params": {"length": PROBE_LENGTH, "format": mrs.LFDR_FORMAT},
        "requires_key": False,
        "key_header_sent": False,
        "checked_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    try:
        batch = await client.fetch(length=PROBE_LENGTH)
    except mrs.AnuError as exc:
        out.update({"status": "error", "code": exc.code, "reason": exc.reason,
                    "sent": exc.sent,
                    "elapsed_ms": int((time.perf_counter() - started) * 1000)})
        return out
    out.update({
        "status": "ok",
        "provider": batch.provider,
        "entropy_class": mrs.entropy_class_for(batch.provider),
        "data_type": batch.data_type,
        "declared_length": batch.length,
        "values_count": len(batch.values),
        "qrn_hex_len": batch.length * 2,
        "values_uint8": all(0 <= value <= 255 for value in batch.values),
        "sample_hex": "".join(f"{value:02x}" for value in batch.values),
        "adapter_latency_ms": batch.latency_ms,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "breaker": client.status(),
    })
    return out


if __name__ == "__main__":
    print(json.dumps(asyncio.run(main()), ensure_ascii=False, indent=2))
