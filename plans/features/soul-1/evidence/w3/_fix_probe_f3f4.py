"""FIX-W3 probe: F3 (payload-проверка до egress-guard) и F4 (nostalgia мимо прохода).

Запуск: .venv\\Scripts\\python.exe <scratch>\\fix-w3\\_fix_probe_f3f4.py
"""
from __future__ import annotations

import asyncio
import sys

from services import chat_params
from services import hot_config as hot
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


def enable(doc):
    import os
    os.environ["SPEECH_STYLE_POLICY_ENABLED"] = "1"
    hot.set_config_cache(FakeHot({"flags.speech_style_policy_enabled": True,
                                  sp.DOC_KEY: doc}))
    chat_params.set_chat_params_cache(FakeChatCache())


async def main() -> int:
    doc = sp.build_document(presets=["no_quotes", "no_trailing_period",
                                     "no_emoji"], owner=1, reason="probe")
    enable(doc)
    sp.reset_repetition_state()

    print("=== F3: проверяется ли payload ПОСЛЕ egress-guard ===")
    answer = "Готово. fact:123"
    outcome = await sp.apply_style_policy(answer, chat_id=CHAT)
    print(f"  pre-send text (стилизованный) : {outcome.text!r}")
    print(f"  payload_status до доставки    : {outcome.payload_status!r}")
    bot = RecordingBot()
    await DirectChatService._send_direct_answer(
        bot, CHAT, outcome.text, None, style_outcome=outcome)
    print(f"  ФАКТИЧЕСКИ доставлено         : {bot.sent[0][1]!r}")
    print(f"  payload_status после доставки : {outcome.payload_status!r}")
    print(f"  styled={outcome.styled}")

    print()
    print("=== F4: nostalgia/prepared_text идёт ли через проход формы ===")
    enable(doc)
    sp.reset_repetition_state()
    bot = RecordingBot()
    cand = mi.candidate_from_trigger(
        trigger_kind="nostalgia_due", chat_id=CHAT, source="nostalgia",
        prepared_text_ref="nostalgia:1", reason_code="default")
    situation = mi.InitiativeSituation(trigger_kind="nostalgia_due",
                                       chat_id=CHAT)
    result = await handle_initiative(
        bot=bot, chat_id=CHAT, situation=situation, candidates=[cand],
        prepared_text="Он сказал «база это сила». 😀", db=None)
    print(f"  status={result.get('status')!r}")
    print(f"  доставлено: {[t for _c, t in bot.sent]!r}")
    print("  ожидание после фикса: кавычки/эмодзи сняты, точки нет "
          "(тот же проход, что в Direct)")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
