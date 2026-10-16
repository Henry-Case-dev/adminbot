"""FIX-W3 probe: воспроизведение F1 (JSON не защищён) и F2 (срезание хвоста).

Не тест полосы — независимый зонд. Запуск:
  .venv\\Scripts\\python.exe <scratch>\\fix-w3\\_fix_probe_f1f2.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import sys

from services import chat_params
from services import hot_config as hot
from services import style_policy as sp

CHAT_A = 101


class FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value, **kwargs):
        self.values[key] = value


class FakeChatCache:
    def __init__(self, overrides=None):
        self.overrides = dict(overrides or {})

    async def get_chat_params(self, chat_id):
        return {"overrides": dict(self.overrides.get(int(chat_id), {}))}


def enable(doc):
    import os
    os.environ["SPEECH_STYLE_POLICY_ENABLED"] = "1"
    hot.set_config_cache(FakeHot({"flags.speech_style_policy_enabled": True,
                                  sp.DOC_KEY: doc}))
    chat_params.set_chat_params_cache(FakeChatCache({}))


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def rep(text: str) -> str:
    return repr(text)


F1_CASES = [
    '{"path": "/api/v1/x"}',
    'Данные: {"note": "ok"} — вот.',
    '{"call": "print(x)"}',
    'Вот ответ: {"a": {"b": [1, 2]}, "c": "x"} и всё.',
    'Смотри [{"id": 1, "url": "https://example.org/x"}] — список.',
    'Итог: {"msg": "он сказал \\"да\\""} готово',
    '{"k": "v"}.',
    'Фрагмент {"k": "v"} в строке.',
]

F2_CASES = [
    # (предыдущая реплика бота, вход)
    ("Ну да, это классика жанра, как обычно.",
     "Ну да, это классика жанра. И это важный нюанс."),
    ("Ну да, это классика жанра, как обычно.",
     "Ну да, это классика жанра. И это важный нюанс, который стоит учесть."),
    ("Ну да, это классика жанра, как обычно.",
     "Разбор простой. Ну да, это классика жанра."),
]


async def main() -> int:
    doc = sp.build_document(presets=["no_quotes", "no_trailing_period"],
                            owner=1, reason="probe")
    print("=== F1: JSON под hard-правилами (no_quotes + no_trailing_period) ===")
    for raw in F1_CASES:
        enable(doc)
        sp.reset_repetition_state()
        outcome = await sp.apply_style_policy(raw, chat_id=CHAT_A)
        same = outcome.text == raw
        print(f"  in : {rep(raw)}")
        print(f"  out: {rep(outcome.text)}   byte_identical={same} "
              f"sha_in={sha(raw)} sha_out={sha(outcome.text)}")
        print(f"  statuses: repaired={outcome.repaired} exempted={outcome.exempted}"
              f" conflicts={outcome.conflicts} styled={outcome.styled}"
              f" reasons={[(r.kind, r.status, r.reason) for r in outcome.results]}")
        print()

    print("=== F2: повтор в ПЕРВОМ предложении, посторонний хвост ===")
    for prev, raw in F2_CASES:
        enable(doc)
        sp.reset_repetition_state()
        sp.record_bot_output(CHAT_A, prev)
        outcome = await sp.apply_style_policy(raw, chat_id=CHAT_A)
        print(f"  prev: {rep(prev)}")
        print(f"  in  : {rep(raw)}")
        print(f"  out : {rep(outcome.text)}  changed={outcome.text != raw}")
        print(f"  repetition={outcome.repetition}")
        print()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
