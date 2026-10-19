"""Pre-registration: F3 eval prompts disjoint from few-shot + acceptance-96/97."""
from __future__ import annotations

import ast
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[6]
OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "disjoint-check.json")
sys.path.insert(0, str(ROOT))

import services.mca_sample_library as sl  # noqa: E402

FEWSHOT = [x["input_text"] for x in sl.EXPRESSION_STARTER_SAMPLES]
ACC96 = [
    "бот, ну ты и выдал вчера с этим докладом, весь чат ржал",
    "бот, твой вариант вообще не работает, я вчера проверял на сервере",
    "бот, пойдёшь завтра с нами?",
    "бот, интернет опять отвалился, роутер перезагрузил - не помогло",
    "бот, расскажи короткую шутку про понедельник",
    "бот, напомни, какой командой посмотреть занятое место на диске",
    "бот, проверь факт: у осьминога три сердца",
    "бот, передай дословно, что написал Вася: «да пошёл он нахуй со "
    "своими правками, я устал»",
    "бот, ну ты и выдал вчера с докладом, до сих пор вспоминаю",
    "бот, твой вариант не работает, я его на стенде гонял полдня",
    "бот, ты завтра с нами?",
    "бот, интернет снова отвалился, куда смотреть в первую очередь?",
    "бот, расскажи короткую шутку про дедлайны",
    "бот, какой командой посмотреть размер папки на сервере?",
    "бот, это правда, что у осьминога три сердца?",
    "бот, ну ты и выдал вчера с докладом, это было эпично",
    "бот, твой вариант вообще не работает, я на него полдня убил",
    "бот, ты в деле завтра?",
    "бот, интернет опять сдох, уже третий раз за вечер",
    "бот, расскажи короткую шутку про понедельник и дедлайны",
    "бот, чем посмотреть топ процессов по памяти? коротко",
    "бот, проверь: у осьминога три сердца или одно?",
    "бот, сделай короткую тех-сводку: сервер admin-bot, версия 2.58.96, "
    "диск занят на 68%, память 961 МБ, аптайм 5 дней",
    "бот, интернет лагает второй день, что проверить в первую очередь?",
    "бот, твой вариант не работает, я его вдоль и поперёк проверил",
]

#: acceptance-97 (F4) prompts — из harness, без исполнения кода.
ACC97_PATH = (ROOT / "plans" / "features" / "add-exp" / "evidence" / "f4" /
              "harness" / "accept97_live.py")
TREE = ast.parse(ACC97_PATH.read_text(encoding="utf-8"))
CONST = {}
for node in TREE.body:
    if isinstance(node, ast.Assign) and len(node.targets) == 1 \
            and isinstance(node.targets[0], ast.Name) \
            and node.targets[0].id in ("FREQ_CONV", "OCC_CONV", "OFF_CONV",
                                       "FREQ_SUMMARY", "OFF_QUOTE"):
        CONST[node.targets[0].id] = ast.literal_eval(node.value)
ACC97 = []
for key in ("FREQ_CONV", "OCC_CONV", "OFF_CONV"):
    ACC97 += [item[2] for item in CONST[key]]
for key in ("FREQ_SUMMARY", "OFF_QUOTE"):
    ACC97.append(CONST[key][2])

#: F3 eval prompts (10 разговорных + 3 исключения) из harness.
spec = importlib.util.spec_from_file_location(
    "eval_directives", str(Path(__file__).with_name("eval_directives.py")))
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def toks(s: str) -> list[str]:
    return re.findall(r"[а-яёa-z0-9]+", str(s or "").lower())


def ngrams(ts: list[str], n: int = 3) -> set[str]:
    return {" ".join(ts[i:i + n]) for i in range(max(0, len(ts) - n + 1))}


CORPUS = FEWSHOT + ACC96 + ACC97
MINE = [(sid, p, "conversational") for sid, p in mod.SCENARIOS] + [
    (e["id"], e["prompt"], "genre") for e in mod.EXCEPTIONS]

report = {"corpus": {"fewshot": len(FEWSHOT), "acc96": len(ACC96),
                     "acc97": len(ACC97), "total": len(CORPUS)},
          "prompts": []}
for sid, prompt, group in MINE:
    tp = toks(prompt)
    np_ = ngrams(tp)
    rec = {"id": sid, "prompt": prompt, "group": group,
           "max_jaccard": 0.0, "shared_3grams": []}
    for other in CORPUS:
        to = toks(other)
        j = len(set(tp) & set(to)) / max(1, len(set(tp) | set(to)))
        shared = sorted(np_ & ngrams(to))
        if j > rec["max_jaccard"]:
            rec["max_jaccard"] = round(j, 3)
            rec["closest"] = other
        if shared:
            rec["shared_3grams"].append({"with": other, "grams": shared})
    report["prompts"].append(rec)

conv = [r for r in report["prompts"] if r["group"] == "conversational"]
gen = [r for r in report["prompts"] if r["group"] == "genre"]
report["conversational"] = {
    "max_jaccard": max(r["max_jaccard"] for r in conv),
    "shared_3grams": [(r["id"], r["shared_3grams"]) for r in conv
                      if r["shared_3grams"]],
}
report["genre"] = {
    "max_jaccard": max(r["max_jaccard"] for r in gen),
    "shared_3grams": [(r["id"], r["shared_3grams"]) for r in gen
                      if r["shared_3grams"]],
    "note": "исключения совпадают по ЖАНРУ (фактчек/цитата/просьба), "
            "формулировки и данные различаются",
}
report["verdict"] = ("PASS" if report["conversational"]["max_jaccard"] < 0.30
                     and not report["conversational"]["shared_3grams"]
                     else "FAIL")
OUT.write_text(json.dumps(report, ensure_ascii=False, indent=1),
               encoding="utf-8")
print(json.dumps({"corpus": report["corpus"],
                  "conversational": report["conversational"],
                  "genre": report["genre"],
                  "verdict": report["verdict"]}, ensure_ascii=False, indent=1))
