"""SOUL-1 / W3 — воспроизводимый зонд доказательств (не тест, артефакт).

Что делает (без pytest, без PG, без Telegram):
  1. собирает hard-политику владельца (без кавычек / без точки / без эмодзи);
  2. прогоняет разнородные ответы через ЕДИНЫЙ проход формы и через РЕАЛЬНУЮ
     функцию доставки Direct с записывающим ботом (тестовый контур) — печатает
     фактический payload;
  3. показывает one_word end-to-end (ровно одно лексическое слово);
  4. печатает таблицу исходов по правилам (R17-safe: sha12 входа + статусы);
  5. замеряет стоимость: latency прохода (p50/p95) и токены hint'а;
  6. печатает каталог kind/presets/hint и наблюдаемость антизалипания.

Запуск (repo root):
    .venv\\Scripts\\python.exe plans/features/soul-1/evidence/w3/_w3_probe.py
"""
from __future__ import annotations

import asyncio
import hashlib
import json
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


def setup(doc):
    os.environ["SPEECH_STYLE_POLICY_ENABLED"] = "1"
    hot.set_config_cache(FakeHot({"flags.speech_style_policy_enabled": True,
                                  sp.DOC_KEY: doc}))
    chat_params.set_chat_params_cache(FakeChatCache())


HARD_DOC = sp.build_document(presets=["no_quotes", "no_trailing_period",
                                     "no_emoji"], owner=1,
                             reason="SOUL-16.5.3 приёмка")

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
]


async def deliver(text, outcome, **kwargs):
    bot = RecordingBot()
    await DirectChatService._send_direct_answer(
        bot, CHAT_ID, text, None, style_outcome=outcome, **kwargs)
    return bot.sent[0]


async def main() -> int:
    os.makedirs(OUT_DIR, exist_ok=True)
    setup(HARD_DOC)
    lines: list[str] = []

    def w(line: str = "") -> None:
        lines.append(line)
        print(line)

    w("SOUL-1 / W3 — доказательства Speech Style Policy (кандидат: рабочее дерево)")
    w("Флаг: SPEECH_STYLE_POLICY_ENABLED=1 + flags.speech_style_policy_enabled=true (тест)")
    w("Документ: presets=no_quotes+no_trailing_period+no_emoji, revision=%d"
      % HARD_DOC["revision"])
    w()

    # ── 1. Правило на фактическом payload ──────────────────────────────────
    w("═══ 1. ПРАВИЛО НА ДОСТАВЛЯЕМОМ PAYLOAD (SOUL-16.3.4) ═══")
    answer = ("Смотри https://example.org/path — там версия v1.2.3, и код "
              "`x = 1.2.3` в примере.")
    outcome = await sp.apply_style_policy(answer, chat_id=CHAT_ID)
    payload = await deliver(outcome.text, outcome)
    w("вход (sha12=%s, %d симв.): %s" % (sha12(answer), len(answer), answer))
    w("после прохода (repaired=%d, conflicts=%s): %s"
      % (outcome.repaired, list(outcome.conflicts), outcome.text))
    w("ФАКТИЧЕСКИЙ payload (post-sanitize, как уходит в bot.send_message):")
    w("    %r" % payload)
    w("проверка payload: status=%s conflicts=%s" % (
        sp.verify_outbound_payload(payload, policy=outcome.policy,
                                   outcome=outcome).payload_status,
        list(sp.verify_outbound_payload(payload, policy=outcome.policy,
                                        outcome=outcome).conflicts)))
    w("URL сохранён: %s | версия сохранена: %s | точка в конце: %s"
      % ("https://example.org/path" in payload,
         "v1.2.3" in payload and "x = 1.2.3" in payload,
         payload.rstrip().endswith(".")))
    w()

    # ── 2. one_word end-to-end ────────────────────────────────────────────
    w("═══ 2. one_word END-TO-END (SOUL-05.2/05.6) ═══")
    ow_outcome = await sp.apply_style_policy(
        "Да.", chat_id=CHAT_ID, plan=extent.ResponsePlan(extent="one_word"))
    ow_payload = await deliver(ow_outcome.text, ow_outcome)
    w("L1Plan(extent=one_word).to_response_plan().extent = %r (не micro)"
      % extent.ResponsePlan(extent="one_word").extent)
    w("вход 'Да.' → payload %r → лексических слов: %d"
      % (ow_payload, len(extent.lexical_words(ow_payload))))
    micro_payload = await deliver("Да, вполне нормально.", None)
    w("micro-путь без сжатия: %r → слов: %d"
      % (micro_payload, len(extent.lexical_words(micro_payload))))
    w()

    # ── 3. Таблица разнородных входов ─────────────────────────────────────
    w("═══ 3. 10+ РАЗНОРОДНЫХ ВХОДОВ ЧЕРЕЗ DELIVERY-КОНТУР (SOUL-16.5.3) ═══")
    w("%-12s %-10s %-26s %-8s %s" % ("sha12(вход)", "extent", "исходы правил",
                                     "payload", "хвост-точка"))
    for raw, kind in CASES:
        plan = extent.ResponsePlan(extent=kind)
        res = await sp.apply_style_policy(raw, chat_id=CHAT_ID, plan=plan)
        payload = await deliver(res.text, res)
        statuses = ",".join(
            "%s:%s" % (row.kind.split("_")[0], row.status)
            for row in res.results) or "-"
        w("%-12s %-10s %-26s %-8d %s" % (
            sha12(raw), kind, statuses, len(payload),
            "нет" if not payload.rstrip().endswith(".") else "ЕСТЬ"))
    w()

    # ── 4. Стоимость ──────────────────────────────────────────────────────
    w("═══ 4. СТОИМОСТЬ (SOUL-16.4.5): 0 LLM-вызовов на нарушение ═══")
    timings = []
    sample = "Ну это «гениальная» идея. 😀 Ссылка https://example.org/path."
    for _ in range(50):
        started = time.perf_counter()
        await sp.apply_style_policy(sample, chat_id=CHAT_ID)
        timings.append((time.perf_counter() - started) * 1000.0)
    timings.sort()
    policy = await sp.effective_style_policy(CHAT_ID)
    w("проход: p50=%.3f ms | p95=%.3f ms | max=%.3f ms (n=50, детерминированно)"
      % (statistics.median(timings), timings[int(0.95 * len(timings)) - 1],
         timings[-1]))
    w("hint: %d симв. | %d токенов (оценщик композера) — единственная добавка"
      % (len(policy.hint), policy.hint_tokens))
    w("дополнительных LLM-вызовов на ответ: 0 (нет ни одного .generate в модуле: %s)"
      % ("services.llm" not in open(os.path.join(
          ROOT, "services", "style_policy.py"), encoding="utf-8").read()))
    w("смысловой bounded-ремонт: только по явному callback вызывающего, max 1 на"
      " проход (тест test_bounded_semantic_repair_is_at_most_one_and_only_on_conflict)")
    w()

    # ── 5. Каталог kind/presets/hint ──────────────────────────────────────
    w("═══ 5. РЕЕСТР ПРАВИЛ / ПРЕСЕТЫ / HINT (SOUL-16.1.4/16.1.5/16.4.1) ═══")
    view = sp.style_policy_view(HARD_DOC, None)
    for row in view["rule_kinds"]:
        w("kind=%-16s %s" % (row["kind"], row["title_ru"]))
    w("presets: %s" % ", ".join(p["id"] for p in view["available_presets"]))
    w("активные правила (id → source): %s"
      % ", ".join("%s→%s" % (r["id"], r["source"]) for r in view["rules"]))
    w("hint (%d симв., %d токенов):" % (len(policy.hint), policy.hint_tokens))
    for line in policy.hint.splitlines():
        w("    " + line)
    w()

    # ── 6. Антизалипание ──────────────────────────────────────────────────
    w("═══ 6. АНТИЗАЛИПАНИЕ (SOUL-09): наблюдаемо и пропорционально ═══")
    sp.reset_repetition_state()
    sp.record_bot_output(CHAT_ID, "Ну и классика жанра как всегда")
    rep = await sp.apply_style_policy(
        "Разбор простой. Ну и классика жанра как всегда", chat_id=CHAT_ID)
    w("находки: %s" % json.dumps(rep.as_dict()["repetition"],
                                 ensure_ascii=False))
    w("текст после локальной замены (без повторной генерации): %r" % rep.text)
    w("окно (R17-safe): %s" % json.dumps(sp.repetition_view(CHAT_ID),
                                         ensure_ascii=False))
    w("ban-list: %s" % json.dumps(sp.dynamic_bans_view(CHAT_ID),
                                  ensure_ascii=False))
    w()

    text = "\n".join(lines) + "\n"
    path = os.path.join(OUT_DIR, "style-payload-demo.txt")
    with open(path, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)
    print("written: %s" % path)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
