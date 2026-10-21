# -*- coding: utf-8 -*-
"""EXPRESSION-BISECT фаза 3 — плечо H_expr_bare:
полный system, Expression-блок заменён на «голую» frequent-строку без
шапки-нейтрализаторов и без строк Остроумия/Резкости, позиция — в конце
(та же позиция, где C давал 2/4, а F с полным блоком — 0/4).
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

BARE_BLOCK = ("<Expression_Settings>\n"
              "- Мат: используй мат, пиши как двачер.\n"
              "</Expression_Settings>")


def bare_expr_at_end(system: str) -> str:
    start = system.index("<Expression_Settings>")
    end = system.index("</Expression_Settings>") + len("</Expression_Settings>")
    rest = (system[:start] + system[end:]).replace("\n\n\n", "\n\n")
    return rest.rstrip("\n") + "\n\n" + BARE_BLOCK


async def main() -> int:
    t0 = time.time()
    report = json.loads(RESULTS.read_text(encoding="utf-8"))
    sys_full, _ = await bm.build_full_system()
    system = bare_expr_at_end(sys_full)
    (OUT / "system_H_expr_bare.txt").write_text(
        system + "\n", encoding="utf-8", newline="\n")
    from services.llm_client import LLMClient
    llm = LLMClient(bm.settings.LLM_BASE_URL, bm.settings.LLM_API_KEY,
                    bm.settings.LLM_MODEL_NAME,
                    bm.settings.EMBEDDING_MODEL_NAME)
    rows = await bm.generate(llm, system, "H_expr_bare", 4)
    report["arms"]["H_expr_bare"] = {
        "runs": rows,
        "mat_present_n": sum(1 for r in rows if r.get("mat_present")),
        "mat_roots_total": sum(int(r.get("mat_roots") or 0) for r in rows),
        "avg_chars": round(sum(r.get("reply_chars") or 0 for r in rows)
                           / max(1, len(rows)), 0),
    }
    report["calls"] = bm.CALLS["llm"] + int(report.get("calls") or 0)
    report["elapsed_total_s"] = round(time.time() - t0, 1)
    RESULTS.write_text(
        json.dumps(report, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8", newline="\n")
    print("BISECT PHASE3 DONE", flush=True)
    return 0


if __name__ == "__main__":
    try:
        rc = asyncio.run(main())
    except Exception as exc:                          # noqa: BLE001
        import traceback
        (HERE.parent / "harness-error-phase3.log").write_text(
            traceback.format_exc(), encoding="utf-8")
        print("BISECT PHASE3 FATAL %s: %s" % (
            type(exc).__name__, str(exc)[:300]))
        rc = 4
    sys.exit(rc)
