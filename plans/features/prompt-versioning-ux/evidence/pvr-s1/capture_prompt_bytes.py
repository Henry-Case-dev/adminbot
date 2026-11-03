"""PVR-S1 — байт-эталон действующих текстов промптов (жёсткое ограничение пакета).

Пакет EPIC-PROMPT-VERSIONING-UX-01 запрещает менять тексты промптов. Скрипт
снимает SHA-256 и длину в байтах КАЖДОГО pg-управляемого блока реестра из
живого слоя конфигурации процесса (``services.prompt_registry.factory_text``)
и пишет JSON. Повторный прогон после правок и после деплоя даёт те же хеши —
это и есть сверка «байт-в-байт».

Запуск (из корня проекта)::

    python plans/features/prompt-versioning-ux/evidence/pvr-s1/capture_prompt_bytes.py \\
        --out plans/features/prompt-versioning-ux/evidence/pvr-s1/prompt-bytes-baseline.json

Действующий (эффективный) текст конкретного чата живёт в production
``chat_profiles.overrides`` / ``bot_settings``; он снимается отдельно на
деплое (тот же скрипт + чтение PG). В этом пакете байты владельца не
записываются.
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import pathlib
import sys


def snapshot() -> dict:
    root = pathlib.Path(__file__).resolve()
    for parent in root.parents:
        if (parent / "services" / "prompt_registry.py").exists():
            sys.path.insert(0, str(parent))
            break
    else:                                   # pragma: no cover — сломанный путь
        raise RuntimeError("project root not found")
    from services import prompt_registry as pr

    blocks: dict[str, dict] = {}
    for spec in sorted(pr.all_blocks(), key=lambda s: s.block_id):
        if not spec.pg_key:
            continue
        text = pr.factory_text(spec.block_id)
        body = text.encode("utf-8")
        blocks[spec.block_id] = {
            "pg_key": spec.pg_key,
            "ui": spec.ui,
            "doc_field": getattr(spec, "pg_doc_field", "") or "",
            "sha256": hashlib.sha256(body).hexdigest(),
            "bytes": len(body),
            "sha256_12": pr.sha12(text),
            "sealed": pr.sealed_factory_revision(spec.block_id),
        }
    aggregate = hashlib.sha256(
        json.dumps({k: v["sha256"] for k, v in blocks.items()},
                   sort_keys=True).encode()).hexdigest()
    return {
        "kind": "prompt-bytes-baseline",
        "epic": "EPIC-PROMPT-VERSIONING-UX-01",
        "slice": "PVR-S1 write layer / PVR-S0 guard",
        "captured_at_utc": datetime.datetime.now(
            datetime.timezone.utc).isoformat(timespec="seconds"),
        "source": "services/prompt_registry.factory_text for every pg-managed "
                  "block (live configuration layer of the process)",
        "aggregate_sha256_over_all_block_sha256": aggregate,
        "factory_set_sha256_12": getattr(pr, "FACTORY_SET_SHA256_12", None),
        "block_count": len(blocks),
        "blocks": blocks,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="")
    args = parser.parse_args(argv)
    data = snapshot()
    text = json.dumps(data, ensure_ascii=False, indent=1) + "\n"
    if args.out:
        target = pathlib.Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text, encoding="utf-8")
        print(f"written {target} ({data['block_count']} blocks, "
              f"aggregate={data['aggregate_sha256_over_all_block_sha256']})")
    else:
        print(text, end="")
    return 0


if __name__ == "__main__":      # pragma: no cover — утилита верификации
    raise SystemExit(main())
