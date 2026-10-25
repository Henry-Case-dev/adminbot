#!/usr/bin/env python3
"""Thin stand wrapper for cases C/D/E/F (not product code).

Imports the exact committed harness and replaces ONLY the current message text
in window A. History, timestamps, window rows and product code are untouched.
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
QUESTIONS = {
    "C": "Слушай, а ты дождь любишь или тебя от него тоже ломает?",
    "D": "Бот, скажи прямо, без фильтров: я тебе уже надоел со своими вопросами?",
    "E": "Разбери подробно по этому чату: какие темы реально повторяются чаще всего и кто что обычно пишет? С примерами.",
    "F": "Напомни, что там было с конфликтом в чате на прошлой неделе — кто с кем поругался и из-за чего?",
}


def load_harness():
    path = os.path.join(HERE, "harness_probe_full.py")
    spec = importlib.util.spec_from_file_location("harness_probe_full", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--name", required=True, choices=tuple(QUESTIONS))
    ap.add_argument("--root", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--repeats", type=int, default=2)
    args = ap.parse_args()

    hp = load_harness()
    question = QUESTIONS[args.name]
    original = hp.load_sqlite

    def patched(root):
        sq = original(root)
        hits = 0
        for row in sq.get("window_A") or []:
            if str(row.get("tg_message_id")) == str(hp.TG_A):
                row["text"] = question
                hits += 1
        sq["extra_question"] = question
        sq["extra_hits"] = hits
        return sq

    hp.load_sqlite = patched
    sys.argv = [
        "harness_probe_full.py",
        "--root", args.root,
        "--label", "new_" + args.name,
        "--case", "A",
        "--repeats", str(args.repeats),
        "--use-code-l1-canon",
        "--out", args.out,
    ]
    return hp.main()


if __name__ == "__main__":
    raise SystemExit(main())
