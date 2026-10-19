"""F3 supplement: frequent в prod-подобном контексте (Core + канон).

3 вызова (≤36 суммарно с eval_directives: 30 + 3 exceptions + 3 = 36).
Core/канон — каноническая тест-фикстура проекта (не боевой Core из БД):
«Разрешен мат и сленг.» + строка Core из test_add_exp_expression.py.
Цель — увидеть, меняется ли частота `frequent` при наличии разрешения Core,
как в боевом payload. Это НЕ приёмка и не замена основной матрицы 10×3.
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT))

from config.settings import settings  # noqa: E402
from services import mca_expression as ex  # noqa: E402
from services.llm_client import LLMClient  # noqa: E402

PERSONA = ("Ты — личный ассистент в личном чате. Отвечай по-русски, живо и "
           "по делу; без списков, если не просят.")
CANON = "Разрешен мат и сленг."
CORE = ("Мат и грубость. Мат - естественная часть речи, разговорная норма. "
        "Используй его свободно, если он делает фразу выразительнее.")
PROMPTS = (
    ("keys", "Забыл ключи дома, стою у подъезда и жду жену. "
             "Успею на электричку в 19:40?"),
    ("friend", "Друг отменил поездку в последний момент, я остался с "
               "арендованной машиной. Ехать одному?"),
    ("dog", "Думаю завести собаку в однушке. Реально или лучше не мучить "
            "животное?"),
)


async def main(out_path: Path) -> int:
    client = LLMClient(
        settings.LLM_BASE_URL, settings.LLM_API_KEY, settings.LLM_MODEL_NAME,
        settings.EMBEDDING_MODEL_NAME)
    layer = ex.render_expression_text(
        ex.resolve_effective({"profanity": "frequent"}, None))
    system = "\n\n".join((PERSONA, CANON, CORE, layer))
    result = {"kind": "supplement_prod_like_context", "acceptance": False,
              "mode": "frequent", "provider_model": settings.LLM_MODEL_NAME,
              "temperature": 0.7, "canon": CANON, "core": CORE,
              "layer_sha12": ex.sha12(layer),
              "system_sha12": ex.sha12(system), "turns": []}
    for sid, prompt in PROMPTS:
        rec = {"scenario": sid, "user": prompt}
        try:
            reply = await client.generate(
                [{"role": "system", "content": system},
                 {"role": "user", "content": prompt}], temperature=0.7)
        except Exception as exc:      # noqa: BLE001
            rec.update({"error": type(exc).__name__,
                        "error_text": str(exc)[:300]})
            result["turns"].append(rec)
            out_path.write_text(json.dumps(result, ensure_ascii=False,
                                           indent=1), encoding="utf-8")
            return 2
        rr = [str(r).lower() for r in ex._PROFANITY_RE.findall(reply)]
        rec.update({"reply": reply, "mat_roots": len(rr), "roots": rr})
        result["turns"].append(rec)
    result["summary"] = {
        "turns": len(result["turns"]),
        "mat_turns": sum(1 for t in result["turns"] if t["mat_roots"]),
        "mat_roots_total": sum(t["mat_roots"] for t in result["turns"]),
    }
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "context-probe.json")
    raise SystemExit(asyncio.run(main(target)))
