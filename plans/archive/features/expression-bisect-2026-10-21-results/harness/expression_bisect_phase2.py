# -*- coding: utf-8 -*-
"""EXPRESSION-BISECT фаза 2 — точечные плечи по итогам A–E:
  F_expr_last — полный system, Expression-блок ПЕРЕНЕСЁН в самый конец
                (после <Style_Policy_Hint>) — проверка позиции/приоритета.
  G_no_hint   — полный system БЕЗ <Style_Policy_Hint> — проверка конкуренции
                «хвостовых НЕ-правил» с frequent-директивой.
TEST-LIFECYCLE: PROVISIONAL owner=EXPRESSION-BISECT
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location(
    "bisect_main", HERE / "expression_bisect_harness.py")
bm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bm)

OUT = bm.OUT
RESULTS = OUT / "bisect-results.json"


def move_expr_to_end(system: str) -> str:
    block_start = system.index("<Expression_Settings>")
    block_end = (system.index("</Expression_Settings>")
                 + len("</Expression_Settings>"))
    block = system[block_start:block_end]
    rest = (system[:block_start] + system[block_end:])
    return rest.rstrip("\n") + "\n\n" + block


def strip_hint(system: str) -> str:
    block_start = system.index("<Style_Policy_Hint>")
    block_end = (system.index("</Style_Policy_Hint>")
                 + len("</Style_Policy_Hint>"))
    return (system[:block_start] + system[block_end:]).replace(
        "\n\n\n", "\n\n").strip()


async def main() -> int:
    t0 = time.time()
    report = json.loads(RESULTS.read_text(encoding="utf-8"))
    sys_full, _ = await bm.build_full_system()
    arms = [
        ("F_expr_last", move_expr_to_end(sys_full), 4),
        ("G_no_hint", strip_hint(sys_full), 4),
    ]
    (OUT / "system_F_expr_last.txt").write_text(
        arms[0][1] + "\n", encoding="utf-8", newline="\n")
    (OUT / "system_G_no_hint.txt").write_text(
        arms[1][1] + "\n", encoding="utf-8", newline="\n")
    from services.llm_client import LLMClient
    llm = LLMClient(bm.settings.LLM_BASE_URL, bm.settings.LLM_API_KEY,
                    bm.settings.LLM_MODEL_NAME,
                    bm.settings.EMBEDDING_MODEL_NAME)
    for tag, system, n in arms:
        rows = await bm.generate(llm, system, tag, n)
        report["arms"][tag] = {
            "runs": rows,
            "mat_present_n": sum(1 for r in rows if r.get("mat_present")),
            "mat_roots_total": sum(int(r.get("mat_roots") or 0)
                                   for r in rows),
            "avg_chars": round(sum(r.get("reply_chars") or 0 for r in rows)
                               / max(1, len(rows)), 0),
        }
    report["calls"] = bm.CALLS["llm"] + int(report.get("calls") or 0)
    report["elapsed_total_s"] = round(time.time() - t0, 1)
    RESULTS.write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    print("BISECT PHASE2 DONE", flush=True)
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
    except Exception as exc:                          # noqa: BLE001
        import traceback
        (HERE.parent / "harness-error-phase2.log").write_text(
            traceback.format_exc(), encoding="utf-8")
        print("BISECT PHASE2 FATAL %s: %s" % (
            type(exc).__name__, str(exc)[:300]))
        rc = 4
    sys.exit(rc)
