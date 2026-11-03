"""PVR-S6: байтовая проверка мемных промптов против снимка PVR-S0/S1.

    py -3 plans/features/prompt-versioning-ux/evidence/pvr-s6/byte_check.py --repo .

Сравнивает `factory_text` действующих `meme_joke`/`meme_image` с
`evidence/pvr-s1/prompt-bytes-baseline.json`. Печатает `MEME BYTES IDENTICAL:
True` и список блоков, чьи байты изменились относительно того снимка (это
могут быть легитимные правки других, уже влитых линий — они печатаются
поимённо, чтобы «чужая» дельта не приписывалась этому срезу).
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import pathlib
import sys

MEME_BLOCKS = ("initiative.meme.joke", "initiative.meme.image")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", default=".")
    args = parser.parse_args()
    root = pathlib.Path(args.repo).resolve()
    sys.path.insert(0, str(root))
    from services import prompt_registry as pr

    baseline = json.load(io.open(
        root / "plans/features/prompt-versioning-ux/evidence/pvr-s1/"
               "prompt-bytes-baseline.json", encoding="utf-8"))
    ok = True
    for block_id in MEME_BLOCKS:
        text = pr.factory_text(block_id) or ""
        sha = hashlib.sha256(text.encode("utf-8")).hexdigest()
        want = baseline["blocks"][block_id]
        same = sha == want["sha256"] and \
            len(text.encode("utf-8")) == want["bytes"]
        ok = ok and same
        print(f"{block_id}: sha256={sha[:12]} baseline={want['sha256'][:12]} "
              f"bytes={len(text.encode('utf-8'))}/{want['bytes']} "
              f"label={pr.FACTORY_REVISION_LABELS.get(block_id)} "
              f"identical={same}")
    changed = [block_id for block_id, row in baseline["blocks"].items()
               if (pr.factory_text(block_id) or "")
               and hashlib.sha256(
                   (pr.factory_text(block_id) or "").encode("utf-8")
               ).hexdigest() != row["sha256"]]
    print("changed since S1 baseline:", len(changed), changed)
    print("MEME BYTES IDENTICAL:", ok)
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
