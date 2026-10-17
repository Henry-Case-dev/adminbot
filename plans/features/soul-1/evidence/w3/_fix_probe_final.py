"""FIX-W3 — финальный зонд на исправленном кандидате (F1–F4 + стоимость/флаги).

Печатает: байтовое сравнение машинного фрагмента (F1), поведение повтора (F2),
порядок payload-проверки (F3), маршрут инициативы (F4), число LLM-вызовов и
состояние оси `SPEECH_STYLE_POLICY_ENABLED` без документа.

Запуск: .venv\\Scripts\\python.exe <scratch>\\fix-w3\\_fix_probe_final.py
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import sys

from services import chat_params
from services import hot_config as hot
from services import llm_client
from services import mca_gates
from services import mca_intents as mi
from services import style_policy as sp
from services.direct_chat_service import DirectChatService, handle_initiative

CHAT = -100500


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


class RecordingBot:
    def __init__(self):
        self.sent: list = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((chat_id, text))

        class _Msg:
            message_id = 1000 + len(self.sent)

        return _Msg()


def enable(doc=None, *, on=True):
    os.environ["SPEECH_STYLE_POLICY_ENABLED"] = "1" if on else "0"
    values = {"flags.speech_style_policy_enabled": bool(on)}
    if doc is not None:
        values[sp.DOC_KEY] = doc
    hot.set_config_cache(FakeHot(values))
    chat_params.set_chat_params_cache(FakeChatCache())


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


HARD = None  # заполняется в main()

#: (payload, машинный фрагмент — обязан быть БАЙТ-в-БАЙТ)
F1_CASES = [
    ('{"path": "/api/v1/x"}', '{"path": "/api/v1/x"}'),
    ('Данные: {"note": "ok"} — вот.', '{"note": "ok"}'),
    ('{"call": "print(x)"}', '{"call": "print(x)"}'),
    ('Вот ответ: {"a": {"b": [1, 2]}, "c": "x"} и всё.',
     '{"a": {"b": [1, 2]}, "c": "x"}'),
    ('Смотри [{"id": 1, "url": "https://example.org/x"}] — список.',
     '[{"id": 1, "url": "https://example.org/x"}]'),
    ('Итог: {"msg": "он сказал \\"да\\""} готово',
     '{"msg": "он сказал \\"да\\""}'),
    ('{"k": "v"}.', '{"k": "v"}'),
    ('Фрагмент {"k": "v"} в строке.', '{"k": "v"}'),
    ('{"note": "ok}', '{"note": "ok}'),
]

F2_CASES = [
    ("Ну да, это классика жанра. И это важный нюанс.", False),
    ("Ну да, это классика жанра. И это важный нюанс, который стоит учесть.",
     False),
    ("Разбор простой. Ну да, это классика жанра.", True),
]
PREV_PHRASE = "Ну да, это классика жанра, как обычно."


async def main() -> int:
    global HARD
    HARD = sp.build_document(presets=["no_quotes", "no_trailing_period"],
                             owner=1, reason="fix-w3 probe")
    soft_only = sp.build_document(presets=["casual_concise"], owner=1)

    print("=== F1: байты машинного фрагмента (hard no_quotes + no_trailing_period)")
    for raw, fragment in F1_CASES:
        enable(HARD)
        sp.reset_repetition_state()
        outcome = await sp.apply_style_policy(raw, chat_id=CHAT)
        if fragment in outcome.text:
            start = outcome.text.find(fragment)
            seen = outcome.text[start:start + len(fragment)]
            ok = sha(fragment) == sha(seen)
            print(f"  fragment_byte_identical={ok} sha_in={sha(fragment)} "
                  f"sha_out={sha(seen)}")
        else:
            print("  fragment_byte_identical=False (фрагмент потерян!)")
        print(f"    in : {raw!r}")
        print(f"    out: {outcome.text!r}")
        print(f"    rules: {[(r.kind, r.status, r.reason) for r in outcome.results]}")

    print()
    print("=== F2: повтор и посторонний хвост (документ без правил формы)")
    for raw, expect_trim in F2_CASES:
        enable(soft_only)
        sp.reset_repetition_state()
        sp.record_bot_output(CHAT, PREV_PHRASE)
        outcome = await sp.apply_style_policy(raw, chat_id=CHAT)
        trimmed = outcome.text != raw
        print(f"  in : {raw!r}")
        print(f"  out: {outcome.text!r}  changed={trimmed} "
              f"expected_trim={expect_trim} "
              f"repaired_flag={any(r.get('repaired') for r in outcome.repetition)}")

    print()
    print("=== F3: порядок (проход → сериализация → egress-guard → проверка → send)")
    enable(HARD)
    sp.reset_repetition_state()
    outcome = await sp.apply_style_policy("Готово. fact:123", chat_id=CHAT)
    bot = RecordingBot()
    await DirectChatService._send_direct_answer(
        bot, CHAT, outcome.text, None, style_outcome=outcome)
    print(f"  pre-send: {outcome.text!r}  delivered: {bot.sent[0][1]!r}  "
          f"payload_status={outcome.payload_status!r} (ожидание: mismatch)")

    print()
    print("=== F4: инициатива (nostalgia prepared_text и writer)")
    hard_full = sp.build_document(presets=["no_quotes", "no_trailing_period",
                                           "no_emoji"], owner=1,
                                  reason="fix-w3 probe")
    enable(hard_full)
    sp.reset_repetition_state()
    bot = RecordingBot()
    cand = mi.candidate_from_trigger(
        trigger_kind="nostalgia_due", chat_id=CHAT, source="nostalgia",
        prepared_text_ref="nostalgia:1", reason_code="default")
    res = await handle_initiative(
        bot=bot, chat_id=CHAT,
        situation=mi.InitiativeSituation(trigger_kind="nostalgia_due",
                                         chat_id=CHAT),
        candidates=[cand], prepared_text="Он сказал «база это сила». 😀", db=None)
    print(f"  nostalgia status={res.get('status')!r} delivered={bot.sent[0][1]!r}")

    print()
    print("=== стоимость: LLM-вызовы на проходе/отправке ===")
    calls = {"n": 0}
    real_post = llm_client.LLMClient._post
    real_post_key = llm_client.LLMClient._post_with_key

    async def counting_post(self, *args, **kwargs):
        calls["n"] += 1
        return await real_post(self, *args, **kwargs)

    async def counting_post_key(self, *args, **kwargs):
        calls["n"] += 1
        return await real_post_key(self, *args, **kwargs)

    llm_client.LLMClient._post = counting_post
    llm_client.LLMClient._post_with_key = counting_post_key
    try:
        enable(HARD)
        sp.reset_repetition_state()
        await sp.apply_style_policy("Он сказал «база это сила». 😀",
                                    chat_id=CHAT)
        bot = RecordingBot()
        await handle_initiative(
            bot=bot, chat_id=CHAT,
            situation=mi.InitiativeSituation(trigger_kind="nostalgia_due",
                                             chat_id=CHAT),
            candidates=[mi.candidate_from_trigger(
                trigger_kind="nostalgia_due", chat_id=CHAT,
                source="nostalgia", prepared_text_ref="nostalgia:2",
                reason_code="default")],
            prepared_text="Данные: «цитата». 😀", db=None)
    finally:
        llm_client.LLMClient._post = real_post
        llm_client.LLMClient._post_with_key = real_post_key
    print(f"  LLM transport calls на проход+отправку: {calls['n']} (ожидание 0)")

    print()
    print("=== ось SPEECH_STYLE_POLICY_ENABLED и отсутствие документа ===")
    enable(None, on=True)
    sp.reset_repetition_state()
    print(f"  код-дефолт W2_GATES['SPEECH_STYLE_POLICY_ENABLED']: "
          f"{mca_gates.W2_GATES.get('SPEECH_STYLE_POLICY_ENABLED')} "
          f"/ сейчас: {mca_gates.speech_style_policy_enabled()}")
    policy = sp.effective_policy_sync(None, None, context="regular")
    print(f"  без документа: rules={len(policy.rules)} "
          f"soft={len(policy.soft_instructions)} "
          f"skip_reason={policy.skip_reason!r} hint={policy.hint!r}")
    raw = "Он сказал «база это сила». 😀"
    outcome = await sp.apply_style_policy(raw, chat_id=CHAT)
    print(f"  текст без документа: byte_identical={outcome.text == raw} "
          f"styled={outcome.styled} repaired={outcome.repaired} "
          f"applied={outcome.applied}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
