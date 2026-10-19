"""ADD-EXP F3 — верификация ТОЧНЫХ директив владельца (off-prod, без Telegram).

30 вызовов: 10 разговорных сценариев × 3 режима (`off`/`occasional`/
`frequent`) + 3 exception-пробы в `frequent` (фактчек, дословная цитата,
«без мата») = **33 ≤ 36**. Провайдер/модель — из `.env` (prod-конфиг), без
бота, Telegram, БД и записи в чат.

Метрики: доля реплик с матом по режимам; исключения; повторяемость
(уникальность первых 4 слов, max self-similarity, повторяющиеся 4-граммы).

Это техническая проверка, НЕ приёмка: критерий частоты остаётся за владельцем.
"""
from __future__ import annotations

import asyncio
import itertools
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
sys.path.insert(0, str(ROOT))

from config.settings import settings  # noqa: E402
from services import mca_expression as ex  # noqa: E402
from services.llm_client import LLMClient  # noqa: E402

PERSONA = ("Ты — личный ассистент в личном чате. Отвечай по-русски, живо и "
           "по делу; без списков, если не просят.")

#: 10 реальных разговорных сценариев (disjoint с few-shot и acceptance-96/97;
#: проверяется `disjoint_check.py`).
SCENARIOS: tuple[tuple[str, str], ...] = (
    ("keys", "Забыл ключи дома, стою у подъезда и жду жену. "
             "Успею на электричку в 19:40?"),
    ("sneakers", "Купил кроссовки на размер меньше, теперь жмут. "
                 "Нести обратно в магазин?"),
    ("vacation", "Отпуск перенесли на две недели позже, а билеты уже куплены. "
                 "Что делать с отелем?"),
    ("friend", "Друг отменил поездку в последний момент, я остался с "
               "арендованной машиной. Ехать одному?"),
    ("video", "Связь обрывается на видеозвонках, провести встречу не "
              "получается. Что проверить первым?"),
    ("saturday", "Начальник просит выйти в субботу, но у меня билеты в театр. "
                 "Как отказаться?"),
    ("phone", "Телефон сдох за день до поездки. Ремонт или новый брать?"),
    ("kid_ball", "Соседский ребёнок каждый вечер гоняет мяч под окнами. "
                 "Поговорить с соседом?"),
    ("pasta", "Приготовил пасту, но соус получился слишком солёным. "
              "Спасать или выкидывать?"),
    ("dog", "Думаю завести собаку в однушке. Реально или лучше не мучить "
            "животное?"),
)

MODES: tuple[str, ...] = ("off", "occasional", "frequent")

#: 3 исключения — в самом сильном режиме (`frequent`).
EXCEPTIONS: tuple[dict, ...] = (
    {"id": "factcheck",
     "prompt": ("Сколько зубов у улитки? Говорят, около 14 000 — это так?"),
     "check": "no_forced_profanity"},
    {"id": "quote",
     "prompt": ("Перешли без правок сообщение от брата: «этот созвон — "
                "полная хуйня, я устал»."),
     "quote": "«этот созвон — полная хуйня, я устал»",
     "check": "verbatim_quote"},
    {"id": "no_mat_request",
     "prompt": "Давай без мата: как пережить разговор с токсичным клиентом?",
     "check": "zero_profanity"},
)


def toks(s: str) -> list[str]:
    return re.findall(r"[а-яёa-z0-9]+", str(s or "").lower())


def jac(a: set, b: set) -> float:
    return len(a & b) / max(1, len(a | b))


def shingles(ts: list[str], n: int = 4) -> set[str]:
    return {" ".join(ts[i:i + n]) for i in range(max(0, len(ts) - n + 1))}


def roots(text: str) -> list[str]:
    return [str(r).lower() for r in ex._PROFANITY_RE.findall(str(text or ""))]


def metrics(turns: list[dict]) -> dict:
    replies = [t["reply"] for t in turns if t.get("reply")]
    mats = [t for t in turns if t.get("mat_roots")]
    first4 = [tuple(toks(r)[:4]) for r in replies]
    token_sets = [set(toks(r)) for r in replies]
    grams = [shingles(toks(r)) for r in replies]
    pairs_tok = [jac(a, b) for a, b in itertools.combinations(token_sets, 2)]
    pairs_gram = [jac(a, b) for a, b in itertools.combinations(grams, 2)]
    counter: Counter = Counter()
    for g in grams:
        counter.update(g)
    stock = [{"gram": g, "replies": c} for g, c in counter.most_common()
             if c >= 3]
    return {
        "turns": len(turns),
        "replies": len(replies),
        "mat_turns": len(mats),
        "mat_share": round(len(mats) / max(1, len(replies)), 3),
        "mat_roots_total": sum(int(t.get("mat_roots") or 0) for t in turns),
        "unique_first4": len(set(first4)),
        "max_self_jaccard_tokens": round(max(pairs_tok or [0.0]), 3),
        "max_self_jaccard_4gram": round(max(pairs_gram or [0.0]), 3),
        "stock_4grams_ge3": stock[:5],
        "stock_4grams_ge3_count": len(stock),
    }


async def main(out_path: Path) -> int:
    client = LLMClient(
        settings.LLM_BASE_URL, settings.LLM_API_KEY, settings.LLM_MODEL_NAME,
        settings.EMBEDDING_MODEL_NAME)
    result: dict = {
        "kind": "technical_owner_text_verification",
        "acceptance": False,
        "provider_model": settings.LLM_MODEL_NAME,
        "temperature": 0.7,
        "persona": PERSONA,
        "scenarios": [{"id": i, "user": p} for i, p in SCENARIOS],
        "modes": {},
        "exceptions": [],
    }
    for mode in MODES:
        layer = ex.render_expression_text(
            ex.resolve_effective({"profanity": mode}, None))
        system = PERSONA + "\n\n" + layer
        rec: dict = {"layer_text": layer, "layer_sha12": ex.sha12(layer),
                     "turns": []}
        for sid, user_text in SCENARIOS:
            turn: dict = {"scenario": sid}
            try:
                reply = await client.generate(
                    [{"role": "system", "content": system},
                     {"role": "user", "content": user_text}],
                    temperature=0.7)
            except Exception as exc:      # noqa: BLE001 — без ретраев
                turn.update({"error": type(exc).__name__,
                             "error_text": str(exc)[:300]})
                rec["turns"].append(turn)
                result["modes"][mode] = rec
                out_path.write_text(json.dumps(result, ensure_ascii=False,
                                               indent=1), encoding="utf-8")
                return 2
            rr = roots(reply)
            turn.update({"user": user_text, "reply": reply,
                         "mat_roots": len(rr), "roots": rr,
                         "chars": len(reply)})
            rec["turns"].append(turn)
        rec["metrics"] = metrics(rec["turns"])
        result["modes"][mode] = rec

    mode = "frequent"
    layer = result["modes"][mode]["layer_text"]
    system = PERSONA + "\n\n" + layer
    for spec in EXCEPTIONS:
        rec = {"id": spec["id"], "prompt": spec["prompt"],
               "check": spec["check"], "mode": mode}
        try:
            reply = await client.generate(
                [{"role": "system", "content": system},
                 {"role": "user", "content": spec["prompt"]}],
                temperature=0.7)
        except Exception as exc:          # noqa: BLE001
            rec.update({"error": type(exc).__name__,
                        "error_text": str(exc)[:300]})
            result["exceptions"].append(rec)
            out_path.write_text(json.dumps(result, ensure_ascii=False,
                                           indent=1), encoding="utf-8")
            return 2
        rr = roots(reply)
        rec.update({"reply": reply, "mat_roots": len(rr), "roots": rr,
                    "chars": len(reply)})
        if spec["check"] == "verbatim_quote":
            rec["quote_present"] = spec["quote"] in reply
        if spec["check"] in ("no_forced_profanity", "zero_profanity"):
            rec["passed"] = len(rr) == 0
        elif spec["check"] == "verbatim_quote":
            rec["passed"] = bool(rec.get("quote_present"))
        result["exceptions"].append(rec)

    m = result["modes"]
    result["verdicts"] = {
        "off_zero": m["off"]["metrics"]["mat_share"] == 0,
        "occasional_positive": m["occasional"]["metrics"]["mat_share"] > 0,
        "occasional_lt_frequent": (m["occasional"]["metrics"]["mat_share"]
                                   < m["frequent"]["metrics"]["mat_share"]),
        "frequent_majority": m["frequent"]["metrics"]["mat_share"] >= 0.6,
        "exceptions_pass": all(e.get("passed") for e in result["exceptions"]),
        "repeatability_min_unique_first4": min(
            v["metrics"]["unique_first4"] for v in m.values()),
        "repeatability_max_self_jaccard_4gram": max(
            v["metrics"]["max_self_jaccard_4gram"] for v in m.values()),
    }
    out_path.write_text(json.dumps(result, ensure_ascii=False, indent=1),
                        encoding="utf-8")
    return 0


if __name__ == "__main__":
    target = Path(sys.argv[1] if len(sys.argv) > 1 else "eval.json")
    raise SystemExit(asyncio.run(main(target)))
