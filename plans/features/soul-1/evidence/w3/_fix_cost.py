"""FIX-W3 — стоимость прохода после фикса (детерминированно, 0 LLM).

Метод тот же, что в `cost-measurement.txt`: n=50 на вход, p50/p90/p95/max;
плюс проверка bounded-поведения на тексте с большим числом скобок.
"""
from __future__ import annotations

import asyncio
import os
import statistics
import sys
import time

from services import chat_params
from services import hot_config as hot
from services import style_policy as sp

CHAT = 4242
N = 50

INPUTS = [
    "Да.",
    "Ну да, логично.",
    "Он сказал «база», и это была «истина».",
    "Смотри https://example.org/path и https://example.org/other.",
    "Версия v1.2.3 и сборка 2.58.33.",
    "Файл `report.txt` лежит в C:\\data\\report.txt.",
    "Код: print(\"hi\") — работает.",
    'Данные: {"note": "ok", "tags": ["a", "b"]} — вот.',
    'Вот ответ: {"a": {"b": [1, 2]}, "c": "x"} и всё.',
    '{"path": "/api/v1/x"}',
    "Первая строка.\n\n\nВторая строка.",
    "Итого 5\" экран и don't stop",
]


class FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value, **kwargs):
        self.values[key] = value


class FakeChatCache:
    async def get_chat_params(self, chat_id):
        return {"overrides": {}}


def enable(doc):
    os.environ["SPEECH_STYLE_POLICY_ENABLED"] = "1"
    hot.set_config_cache(FakeHot({"flags.speech_style_policy_enabled": True,
                                  sp.DOC_KEY: doc}))
    chat_params.set_chat_params_cache(FakeChatCache())


def stats(samples: list[float]) -> str:
    ordered = sorted(samples)
    p = lambda q: ordered[min(len(ordered) - 1, int(q * len(ordered)))]
    return (f"p50={p(0.50):.3f} ms | p90={p(0.90):.3f} ms | "
            f"p95={p(0.95):.3f} ms | max={max(ordered):.3f} ms")


async def main() -> int:
    doc = sp.build_document(presets=["no_quotes", "no_trailing_period",
                                     "no_emoji"], owner=1, reason="cost probe")
    enable(doc)
    print("FIX-W3 стоимость прохода (hard no_quotes+no_trailing_period+no_emoji)")
    all_samples: list[float] = []
    for raw in INPUTS:
        sp.reset_repetition_state()
        times: list[float] = []
        for _ in range(N):
            started = time.perf_counter()
            await sp.apply_style_policy(raw, chat_id=CHAT)
            times.append((time.perf_counter() - started) * 1000.0)
        all_samples.extend(times)
        print(f"  {len(raw):>4} симв.: {stats(times)}  | {raw[:38]!r}")

    print(f"  ИТОГО n={len(all_samples)}: {stats(all_samples)} "
          f"(база W3: p50=0.207 ms | p95=0.294 ms)")
    print(f"  median всех: {statistics.median(all_samples):.3f} ms")

    # Bounded: текст с большим числом скобок (предел попыток распознавания).
    noisy = " ".join("{x} [y]" for _ in range(400))
    times = []
    for _ in range(5):
        started = time.perf_counter()
        await sp.apply_style_policy(noisy, chat_id=CHAT)
        times.append((time.perf_counter() - started) * 1000.0)
    print(f"  bounded-стресс ({len(noisy)} симв., 800 скобок): {stats(times)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
