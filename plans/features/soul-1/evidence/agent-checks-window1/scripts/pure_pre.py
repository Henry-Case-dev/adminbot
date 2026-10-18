# -*- coding: utf-8 -*-
"""Local pre-run (agent-checks-w1): чистые функции форм/интентов на локальном дереве.

Дерево локально = prod (release/cfg1-2.58.88) для
`services/response_extent.py` и `services/direct_capabilities.py`
(git diff release/cfg1-2.58.88 -- <files> == пусто, см. evidence README).
Печатает матрицы, которые затем сверяются с прогоном на проде.
"""
from __future__ import annotations
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
if str(ROOT) not in sys.path:
    raise SystemExit("path")
import os
os.chdir(ROOT)

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from services import response_extent as rx  # noqa: E402
from services import direct_capabilities as dc  # noqa: E402
from services import smartmodule_phrases as sp  # noqa: E402
from services import smartmodule_throttling as st  # noqa: E402

print("== env: python", sys.version.split()[0])
print("== phrase pool CHAT_COOLDOWN_PHRASES =", len(sp.CHAT_COOLDOWN_PHRASES))
for p in sp.CHAT_COOLDOWN_PHRASES:
    print("   template:", p)

print("== format_remaining_time samples:", [st.format_remaining_time(x)
      for x in (0.4, 45, 90, 270, 300, 3599)])

print("\n== response_extent: check_extent matrix ==")
CASES = [
    ("one_word", "Да!!!"),
    ("one_word", "да"),
    ("one_word", "OK!!!"),
    ("one_word", "по-хорошему"),
    ("one_word", "Да, конечно, всё сделаю"),
    ("one_word", "Готово 🔥"),
    ("one_word", "Да 😀"),
    ("one_word", "Смотри https://example.com/path?q=1"),
    ("one_word", ""),
    ("micro", "ок, будет сделано сегодня"),
    ("micro", "Да!!!"),
    ("micro", "раз два три четыре пять шесть семь восемь девять десять одиннадцать двенадцать"),
    ("compact", "обычный текст без ограничений формы"),
    ("auto", "что угодно"),
]
for extent, text in CASES:
    plan = rx.ResponsePlan(extent=extent)
    res = rx.check_extent(text, plan)
    print(json.dumps({
        "in_extent": extent, "text": text,
        "status": res.status, "reason": res.reason,
        "words": len(res.words or ()),
        "out_text": res.text,
        "changed": (res.text != text),
    }, ensure_ascii=False))

print("\n== direct_capabilities.detect_action_intent matrix ==")
PHRASES = [
    "Бот, нарисуй мем про кота",
    "нарисуй картинку",
    "Сделай мем",
    "сделай мем с текстом",
    "Бот, нарисуй мем, но не рисуй",
    "не рисуй мне мем",
    "придумай концепт мема, рисовать не надо",
    "давай обсудим мемы",
    "я сам нарисую мем",
    "Петя сказал: нарисуй мем",
    "мемориальный комплекс",
    "план на март",
    "уборка в квартире",
    "сделай это",
    "Сделай инфографику по статистике чата",
]
for text in PHRASES:
    it = dc.detect_action_intent(text, addressed=True)
    print(json.dumps({
        "text": text, "intent": it.intent, "confidence": it.confidence,
        "actionable": it.actionable, "reason": it.reason,
        "conceive_only": it.conceive_only, "evidence": list(it.evidence),
    }, ensure_ascii=False))

print("\n== image_generation.is_image_keyword (regex door) ==")
from services import image_generation as ig  # noqa: E402
for text in PHRASES[:7]:
    print(json.dumps({"text": text, "is_keyword": ig.is_image_keyword(text),
                      "prompt": ig.extract_prompt(text)}, ensure_ascii=False))

print("\n== extract_prompt sample:", ig.extract_prompt("Бот, нарисуй простой мем: кот спит на клавиатуре"))
print("== done")
