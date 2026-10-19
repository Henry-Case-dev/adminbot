# -*- coding: utf-8 -*-
"""Pre-registration check: F4 probes are disjoint from few-shot drafts and
from the acceptance-96 phrases (shared 3-gram / token overlap report)."""
from __future__ import annotations

import importlib.util
import json
import re
import sys

LIVE = sys.argv[1]
OUT = sys.argv[2]


def load(path, name):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


M = load(LIVE, "acc97")
sys.path.insert(0, r"C:\Code\Python\adminbot")
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
MINE = ([(p, "conversational") for _, _, p in M.FREQ_CONV]
        + [(p, "conversational") for _, _, p in M.OFF_CONV]
        + [(p, "conversational") for _, _, p in M.OCC_CONV]
        + [(M.FREQ_SUMMARY[2], "genre_summary"),
           (M.OFF_QUOTE[2], "genre_quote")])


def toks(s):
    return re.findall(r"[а-яёa-z0-9]+", s.lower())


def ngrams(ts, n=3):
    return {" ".join(ts[i:i + n]) for i in range(max(0, len(ts) - n + 1))}


REPORT = {"fewshot_inputs": FEWSHOT, "prompt_count": len(MINE), "prompts": []}
worst = []
for p, group in MINE:
    tp, np_ = toks(p), ngrams(toks(p))
    rec = {"prompt": p, "group": group, "max_jaccard": 0.0,
           "shared_3grams": []}
    for other in FEWSHOT + ACC96:
        to = toks(other)
        j = len(set(tp) & set(to)) / max(1, len(set(tp) | set(to)))
        shared = sorted(np_ & ngrams(to))
        if j > rec["max_jaccard"]:
            rec["max_jaccard"] = round(j, 3)
            rec["closest"] = other
        if shared:
            rec["shared_3grams"].append({"with": other, "grams": shared})
    REPORT["prompts"].append(rec)
    worst.append((rec["max_jaccard"], rec["shared_3grams"], p, group))

conv = [r for r in REPORT["prompts"] if r["group"] == "conversational"]
gen = [r for r in REPORT["prompts"] if r["group"].startswith("genre")]
REPORT["conversational"] = {
    "max_jaccard": max(r["max_jaccard"] for r in conv),
    "shared_3grams": [(r["prompt"], r["shared_3grams"]) for r in conv
                      if r["shared_3grams"]],
}
REPORT["genre"] = {
    "max_jaccard": max(r["max_jaccard"] for r in gen),
    "shared_3grams": [(r["prompt"], r["shared_3grams"]) for r in gen
                      if r["shared_3grams"]],
    "note": "жанровые пробы обязаны совпадать по ЖАНРУ (сводка/цитата); "
            "формулировки и данные различаются",
}
REPORT["verdict"] = ("PASS" if REPORT["conversational"]["max_jaccard"] < 0.30
                     and not REPORT["conversational"]["shared_3grams"]
                     else "FAIL")
open(OUT, "w", encoding="utf-8").write(
    json.dumps(REPORT, ensure_ascii=False, indent=1))
print(json.dumps({"prompts": len(MINE),
                  "conversational": REPORT["conversational"],
                  "genre": REPORT["genre"],
                  "verdict": REPORT["verdict"],
                  "worst": sorted(worst, reverse=True)[:3]},
                 ensure_ascii=False, indent=1))
