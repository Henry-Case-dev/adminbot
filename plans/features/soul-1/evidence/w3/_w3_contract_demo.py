"""SOUL-1 / W3 — контракт-демонстрация (артефакт, не тест).

Печатает: per-rule исходы с причинами, фактический payload, проверку сохранности
защищённых фрагментов и контраст one_word/micro. R17-safe: sha12 входов.
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import statistics
import sys
import time

ROOT = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                    "..", "..", "..", "..", ".."))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from services import chat_params  # noqa: E402
from services import hot_config as hot  # noqa: E402
from services import response_extent as extent  # noqa: E402
from services import style_policy as sp  # noqa: E402
from services.direct_chat_service import DirectChatService  # noqa: E402

CHAT_ID = -100777
OUT_DIR = os.path.join(ROOT, "plans", "features", "soul-1", "evidence", "w3")


class FakeHot:
    def __init__(self, values):
        self.values = dict(values)

    def get(self, key, default=None):
        return self.values.get(key, default)

    def set(self, key, value, **kwargs):
        self.values[key] = value


class FakeChatCache:
    async def get_chat_params(self, chat_id):
        return {"overrides": {}}


class RecordingBot:
    def __init__(self):
        self.sent = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append(text)
        return type("M", (), {"message_id": 4242})()


def sha12(text: str) -> str:
    return hashlib.sha256(str(text).encode("utf-8")).hexdigest()[:12]


HARD_DOC = sp.build_document(presets=["no_quotes", "no_trailing_period",
                                     "no_emoji"], owner=1)

CASES = [
    ("Да.", "one_word"),
    ("Ну да, логично.", "micro"),
    ("Он сказал «база», и это была «истина».", "compact"),
    ("Смотри https://example.org/path и https://example.org/other.", "normal"),
    ("Версия v1.2.3 и сборка 2.58.33.", "normal"),
    ("Файл `report.txt` лежит в C:\\data\\report.txt.", "normal"),
    ('Код: print("hi") — работает.', "normal"),
    ("Да, конечно. Вот почему.", "compact"),
    ("Ответ: «цитата источника» внутри строки.", "normal"),
    ("Первая строка.\n\n\nВторая строка.", "compact"),
    ("Что это значит?", "micro"),
    ("Разбор: 1) шаг один; 2) шаг два — итог.", "detailed"),
    ("Итого 5\" экран и don't stop.", "normal"),
]

FRAGMENTS = ("https://example.org/path", "https://example.org/other", "v1.2.3",
             "2.58.33", "`report.txt`", "C:\\data\\report.txt", 'print("hi")',
             "цитата источника", "1) шаг один", "2) шаг два", "5\"", "don't")


async def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    os.environ["SPEECH_STYLE_POLICY_ENABLED"] = "1"
    hot.set_config_cache(FakeHot({"flags.speech_style_policy_enabled": True,
                                  sp.DOC_KEY: HARD_DOC}))
    chat_params.set_chat_params_cache(FakeChatCache())
    lines: list[str] = []

    def w(line: str = "") -> None:
        lines.append(line)

    w("SOUL-1 / W3 — контракт-демонстрация правил формы (кандидат: рабочее дерево)")
    w("Политика: no_quotes + no_trailing_period + no_emoji (hard), revision=%d"
      % HARD_DOC["revision"])
    w("Фрагменты-инварианты проверяются на ФАКТИЧЕСКОМ payload доставки.")
    w()
    for raw, kind in CASES:
        plan = extent.ResponsePlan(extent=kind)
        res = await sp.apply_style_policy(raw, chat_id=CHAT_ID, plan=plan)
        bot = RecordingBot()
        await DirectChatService._send_direct_answer(
            bot, CHAT_ID, res.text, None, style_outcome=res)
        payload = bot.sent[0]
        w("── вход sha12=%s extent=%s (%d симв.)" % (sha12(raw), kind,
                                                     len(raw)))
        w("   payload (%d симв., sha12=%s): %r" % (len(payload), sha12(payload),
                                                   payload))
        for row in res.results:
            w("   %-16s %-12s %-28s %s" % (
                row.kind, row.status, row.reason,
                ",".join("%s=%s" % kv for kv in dict(row.detail).items())))
        if res.extent is not None:
            w("   extent-check     %-12s %s" % (res.extent.status,
                                                res.extent.reason or "-"))
        lost = [frag for frag in FRAGMENTS if frag in raw and frag not in payload]
        w("   защищённые фрагменты сохранены: %s%s"
          % ("да" if not lost else "НЕТ", "" if not lost else f" (потеряно: {lost})"))
        if raw.rstrip().endswith("."):
            w("   завершающая точка на payload: %s"
              % ("нет" if not payload.rstrip().endswith(".") else "ЕСТЬ"))
        w()
    w("═══ контраст режимов ═══")
    for text, kind in (("Да.", "one_word"), ("Да, вполне.", "micro"),
                       ("Ну да, логично, и вот почему.", "micro")):
        res = await sp.apply_style_policy(
            text, chat_id=CHAT_ID, plan=extent.ResponsePlan(extent=kind))
        bot = RecordingBot()
        await DirectChatService._send_direct_answer(
            bot, CHAT_ID, res.text, None, style_outcome=res)
        w("%-8s %-34r → payload %-26r слов=%d статус extent=%s"
          % (kind, text, bot.sent[0], len(extent.lexical_words(bot.sent[0])),
             res.extent_status))
    w()
    w("═══ стоимость (n=50, тот же вход) ═══")
    timings = []
    sample = "Ну это «гениальная» идея. 😀 Ссылка https://example.org/path."
    for _ in range(50):
        started = time.perf_counter()
        await sp.apply_style_policy(sample, chat_id=CHAT_ID)
        timings.append((time.perf_counter() - started) * 1000.0)
    timings.sort()
    policy = await sp.effective_style_policy(CHAT_ID)
    w("p50=%.3f ms | p90=%.3f ms | p95=%.3f ms | max=%.3f ms"
      % (statistics.median(timings), timings[int(0.90 * len(timings)) - 1],
         timings[int(0.95 * len(timings)) - 1], timings[-1]))
    w("hint: %d симв. / %d токенов (единственная добавка к промпту)"
      % (len(policy.hint), policy.hint_tokens))
    w("LLM-вызовов на нарушение: 0 | bounded смысловой ремонт: только по явному "
      "callback вызывающего, max 1/проход")

    text = "\n".join(lines) + "\n"
    for name in ("style-contract-demo.txt", "cost-measurement.txt"):
        with open(os.path.join(OUT_DIR, name), "w", encoding="utf-8",
                  newline="\n") as handle:
            handle.write(text)
    print("written: style-contract-demo.txt, cost-measurement.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
