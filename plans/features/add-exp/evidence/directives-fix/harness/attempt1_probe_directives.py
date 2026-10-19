"""ADD-EXP F2 — ТЕХНИЧЕСКАЯ валидация директив (off-prod, без Telegram).

Что делает: 3 разговорных user-промпта × 3 режима (`off`/`occasional`/
`frequent`) = **9 вызовов** к тому же провайдеру/модели, что в `.env`
(prod-конфиг), без бота, без Telegram, без записи в БД. Система = короткая
нейтральная персона + реальный слой `<Expression_Settings>` из
`services.mca_expression` (новый канон F2).

Это НЕ приёмка: критерий частоты остаётся за владельцем (`EXP-ACCEPT`).
Здесь фиксируется только сила директивы — есть ли обсценные корни в ответах.

Запуск: `.venv\\Scripts\\python.exe probe_directives.py out.json`
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

#: Нейтральная персона: не добавляет своих правил про мат, чтобы измерялся
#: вклад именно директивы режима.
PERSONA = ("Ты — личный ассистент в личном чате. Отвечай по-русски, живо и "
           "по делу; без списков, если не просят.")

#: Три разговорных промпта (бытовая жалоба, раздражение/спор, обычный вопрос).
PROMPTS: tuple[tuple[str, str], ...] = (
    ("everyday", "Слушай, я опять проспал, будильник не сработал. "
                 "Как не проспать завтра?"),
    ("argument", "Коллега опять переписал мой отчёт и не сказал. "
                 "Как ему ответить?"),
    ("neutral", "Как думаешь, стоит ли брать ноутбук в поездку на выходные?"),
)

MODES: tuple[str, ...] = ("off", "occasional", "frequent")


async def main(out_path: Path) -> int:
    client = LLMClient(
        settings.LLM_BASE_URL, settings.LLM_API_KEY, settings.LLM_MODEL_NAME,
        settings.EMBEDDING_MODEL_NAME)
    result: dict = {
        "kind": "technical_directive_validation",
        "acceptance": False,
        "provider_model": settings.LLM_MODEL_NAME,
        "temperature": 0.7,
        "persona": PERSONA,
        "prompts": [{"id": pid, "user": text} for pid, text in PROMPTS],
        "modes": {},
    }
    for mode in MODES:
        layer = ex.render_expression_text(
            ex.resolve_effective({"profanity": mode}, None))
        system = PERSONA + "\n\n" + layer
        mode_rec: dict = {
            "layer_sha12": ex.sha12(layer),
            "system_sha12": ex.sha12(system),
            "mode_line_present": ("- Мат: " + ex.PROFANITY_INSTRUCTIONS[mode]
                                  in layer),
            "layer_text": layer,
            "turns": [],
        }
        for pid, user_text in PROMPTS:
            rec: dict = {"id": pid, "user": user_text}
            try:
                reply = await client.generate(
                    [{"role": "system", "content": system},
                     {"role": "user", "content": user_text}],
                    temperature=0.7)
            except Exception as exc:      # noqa: BLE001 — фиксируем без ретраев
                rec.update({"error": type(exc).__name__,
                            "error_text": str(exc)[:300]})
                mode_rec["turns"].append(rec)
                result["modes"][mode] = mode_rec
                out_path.write_text(
                    json.dumps(result, ensure_ascii=False, indent=1),
                    encoding="utf-8")
                return 2
            roots = [str(r).lower() for r in ex._PROFANITY_RE.findall(reply)]
            rec.update({
                "reply": reply,
                "mat_roots": len(roots),
                "roots": roots,
                "chars": len(reply),
            })
            mode_rec["turns"].append(rec)
        mode_rec["mat_turns"] = sum(1 for t in mode_rec["turns"]
                                    if t.get("mat_roots"))
        mode_rec["mat_roots_total"] = sum(int(t.get("mat_roots") or 0)
                                          for t in mode_rec["turns"])
        result["modes"][mode] = mode_rec
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "probe.json")
    raise SystemExit(asyncio.run(main(target)))
