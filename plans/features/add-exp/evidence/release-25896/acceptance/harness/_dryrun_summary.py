# -*- coding: utf-8 -*-
"""Local dry-run of ACCEPTANCE-96 build_summary with synthetic wave data."""
from __future__ import annotations

import asyncio
import importlib.util

spec = importlib.util.spec_from_file_location(
    "acc96", r"C:\Code\Python\adminbot\OPENCODE_WORKFLOW_SCRATCH\acceptance-96"
             r"\accept96_live.py")
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)


def turn(label, context, mode, answer, status="ok"):
    return {
        "label": label, "chat_id": -1, "mode": mode, "context": context,
        "phrase": "p", "status": status, "error": "",
        "correlation_id": "c", "elapsed_s": 5, "plan_meta": {},
        "sends": [{"kind": "message", "message_id": 1, "text": answer}],
        "answer": answer, "answer_scan": mod.scan_own(answer),
        "sentences": mod.sentence_stats(answer),
        "llm_calls": [], "wire": [], "composes": [], "usage": [],
    }


def wave(mode, contexts):
    return {"wave": mode, "mode": mode, "chat_id": -1,
            "switch": {"write_http": 200, "write_body": {},
                       "reread": {"http": 200, "body": {
                           "effective": {"profanity": {"value": mode,
                                                       "source": "chat"}}}},
                       "resolved": {"mode": mode, "text": "T",
                                    "revision": "r1"}},
            "anchor_mid": 100, "turns": contexts}


waves = {
    "off": wave("off", [
        turn("off-1", "banter", "off", "Выдал, признаю. Зато никто не уснул."),
        turn("off-2", "argument", "off", "У меня крутится стабильно."),
        turn("off-3", "short", "off", "Пойду."),
        turn("off-4", "everyday", "off", "Перезагрузи роутер."),
        turn("off-5", "joke", "off", "Шутка про понедельник: он снова тут."),
        turn("off-6", "tech", "off", "df -h."),
        turn("off-7", "factcheck", "off", "Да, три сердца."),
        turn("off-8", "genre_quote", "off",
             "Передаю дословно: «да пошёл он нахуй со своими правками»"),
    ]),
    "occasional": wave("occasional", [
        turn("occ-1", "banter", "occasional", "Выдал, признаю, бля."),
        turn("occ-2", "argument", "occasional", "Работает стабильно."),
        turn("occ-3", "short", "occasional", "Завтра с вами."),
        turn("occ-4", "everyday", "occasional", "Роутер перезагрузи."),
        turn("occ-5", "joke", "occasional", "Шутка: дедлайн близко."),
        turn("occ-6", "tech", "occasional", "du -sh."),
        turn("occ-7", "factcheck", "occasional", "Да, три."),
        turn("occ-8", "short_repeat", "occasional", "Завтра с вами."),
    ]),
    "frequent": wave("frequent", [
        turn("fr-1", "banter", "frequent", "Ага, выдал, хуёво выдал, бля."),
        turn("fr-2", "argument", "frequent", "Работает, вот и весь хуй."),
        turn("fr-3", "short", "frequent", "В деле, хули."),
        turn("fr-4", "everyday", "frequent", "Интернет сдох, пиздец."),
        turn("fr-5", "joke", "frequent", "Шутка про понедельник, бля."),
        turn("fr-6", "tech", "frequent", "top -o %MEM."),
        turn("fr-7", "factcheck", "frequent", "Да, три сердца."),
        turn("fr-8", "banter_repeat", "frequent", "Выдал, бля, эпично."),
        turn("fr-9", "joke_repeat", "frequent", "Понедельник, пиздец."),
        turn("fr-10", "genre_summary", "frequent",
             "Сводка: версия 2.58.96, диск 68%, память 961 МБ."),
    ]),
}
iso = {"chat_b": -100500, "turns": [
    turn("iso-B-1", "banter", "off", "Выдал, признаю."),
    turn("iso-B-2", "short", "off", "В деле.")],
    "switch_b": {"reread": {"body": {"effective": {"profanity": {
        "value": "off", "source": "chat"}}}}},
    "view_a_while_b_off": {"body": {"effective": {"profanity": {
        "value": "frequent", "source": "chat"}}}},
    "anchor_b_mid": 200}
routes = {"authorial": {"has_marker": True, "mode_line": "frequent"},
          "initiative": {"correlation_id": "c1", "llm_calls": [],
                         "reply": "Интернет, бля, проверьте роутер."}}
p0 = {"view_a": {"body": {"runtime_wired": True}},
      "view_global": {"body": {"document": {"revision": 1}}},
      "preview_eq_resolve": True, "chat_a_overrides": "x",
      "chat_b_overrides": "y"}
p1 = {"seed_run1": {"body": {"seeded": 18, "expression_seeded": 12}},
      "seed_run2": {"body": {"skipped": 18, "expression_skipped": 12}},
      "rows": []}
lc = {"http": 200, "body": {"mode": "frequent", "diag_class": ""}}
restore = {"chat_a": {"http": 200}, "chat_b": {"http": 200},
           "global_view_after": {"body": {"document": {"revision": 1}}},
           "a_view_after": {"body": {"inheritance": "global"}},
           "chat_a_overrides_after": "x", "chat_b_overrides_after": "y"}


class StubBase:
    class CTX:
        db = None

    async def sqlite_fetch(self, sql, args=()):
        return []


async def main():
    summary = await mod.build_summary(StubBase(), waves, iso, routes, p0, p1,
                                      lc, restore, 0, 28, [])
    crit = summary["criteria"]
    for mode in ("off", "occasional", "frequent"):
        c = crit[mode]
        print(mode, "verdict=%s conv=%s/%s share=%s contexts=%s words=%s"
              % (c["verdict"], c["conversational_with_mat"],
                 c["conversational"], c["share"], c["contexts_with_mat"],
                 c["mat_words"]))
    print("quote_preserved:", crit["off"].get("quote_preserved"),
          "quote_own:", crit["off"].get("quote_own_mat"))
    print("summary_facts:", crit["frequent"].get("summary_facts"))
    print("isolation:", crit["isolation"]["verdict"],
          crit["isolation"]["b_own_mat"])
    print("checks keys ok:", sorted(summary["checks"].keys())[:8])
    assert crit["off"]["verdict"] == "PASS"
    assert crit["occasional"]["verdict"] == "PASS"
    assert crit["frequent"]["verdict"] == "PASS", crit["frequent"]
    assert crit["isolation"]["verdict"] == "PASS"
    assert crit["off"]["quote_preserved"] is True
    print("DRYRUN PASS")

asyncio.run(main())
