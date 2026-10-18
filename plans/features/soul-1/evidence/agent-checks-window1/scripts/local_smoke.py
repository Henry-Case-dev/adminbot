# -*- coding: utf-8 -*-
"""Local smoke (agent-checks-w1): проверка заглушек/пути отказа ДО прода.

  * init_data строится и ВАЛИДИРУЕТСЯ aiogram'ом (тест токен);
  * DatabaseService: initialize() -> initialize_existing() на temp-БД;
  * DirectChatService._handle_turn: отказ кулдауна -> фраза -> лог-событие.

Ничего не пишет в прод. Запуск: .venv/Scripts/python.exe <этот файл>.
"""
from __future__ import annotations
import asyncio
import hashlib
import hmac
import json
import os
import sys
import time
import types
import urllib.parse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

TEST_TOKEN = "123456:TEST_TOKEN_AGENT_CHECKS"
SYNTH_CHAT = -1009900000201
SYNTH_USER = 990002001


def make_init_data(user_id: int) -> str:
    fields = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHagentcheck",
        "user": json.dumps({"id": user_id, "first_name": "AgentCheck",
                            "username": "agentcheck"},
                           separators=(",", ":")),
    }
    data_check = "\n".join("%s=%s" % (k, fields[k]) for k in sorted(fields))
    secret = hmac.new(b"WebAppData", TEST_TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(sorted(fields.items())) + "&hash=" + calc


async def main() -> int:
    # 1) init_data — сверка с реализацией aiogram (что валидирует сервер)
    from aiogram.utils.web_app import safe_parse_webapp_init_data
    data = make_init_data(5885953495)
    parsed = safe_parse_webapp_init_data(token=TEST_TOKEN, init_data=data)
    print("SMOKE init_data len=%d parsed_user=%s ok=%s"
          % (len(data), parsed.user.id, parsed.user.id == 5885953495))
    bad = False
    try:
        safe_parse_webapp_init_data(token="000:WRONG", init_data=data)
    except Exception as exc:  # noqa: BLE001
        bad = True
        print("SMOKE init_data wrong-token rejected: %s" % type(exc).__name__)
    assert parsed.user.id == 5885953495 and bad

    # 2) DatabaseService temp
    import tempfile
    from services.database import DatabaseService
    from config.settings import settings
    tmp = Path(tempfile.gettempdir()) / "agent_checks_w1_smoke.db"
    for p in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
        p.unlink(missing_ok=True)
    db = DatabaseService(tmp)
    await db.initialize()
    await db.close()
    db2 = DatabaseService(tmp)
    await db2.initialize_existing()
    cur = await db2.db.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='throttle_state'")
    print("SMOKE sqlite throttle_state exists=%s" % bool(await cur.fetchone()))

    # 3) _handle_turn -> отказ кулдауна (in-memory throttle, llm=None)
    from services.direct_chat_service import DirectChatService, DirectChatThrottle
    from services.summary_aliases import AliasResolver

    class StubBot:
        def __init__(self):
            self.sent = []

        async def send_message(self, chat_id, text, **kwargs):
            self.sent.append((chat_id, str(text), kwargs))
            return types.SimpleNamespace(message_id=999)

        def __getattr__(self, name):
            async def _noop(*a, **k):
                return types.SimpleNamespace(message_id=0)
            return _noop

    thr = DirectChatThrottle(1, 180)
    # прайм: зарядов 0, last_ts=now -> следующий allow даст остаток
    thr._state[(SYNTH_CHAT, SYNTH_USER)] = (0, time.monotonic())
    svc = DirectChatService(memory=None, db=db2, llm=None,
                            aliases=AliasResolver("{}"), throttle=thr,
                            bot_id=8802473181, bot_username="permsoc_bot")
    # глобальный резолв подменит лимиты фабрикой (10/300) — состояние всё равно
    # даёт отказ; ждать нечего: burst_left=0 и cooldown ещё не истёк
    import services.persistent_throttling as pt

    async def fake_resolve(chat_id):
        return 1, 180.0, "chat"
    pt.resolve_direct_chat_limits = fake_resolve  # для smoke-ветки
    # NB: direct_chat_service импортировал функцию напрямую — патчим и там
    import services.direct_chat_service as dcs_mod
    dcs_mod.resolve_direct_chat_limits = fake_resolve

    bot = StubBot()
    msg = types.SimpleNamespace(
        chat=types.SimpleNamespace(id=SYNTH_CHAT, type="supergroup"),
        text="привет", message_id=990000701,
        from_user=types.SimpleNamespace(id=SYNTH_USER, first_name="Probe",
                                        username="probe"),
        reply_to_message=None, caption=None)
    user = types.SimpleNamespace(id=SYNTH_USER, first_name="Probe",
                                 username="probe")
    await svc._handle_turn(bot, msg, user)
    print("SMOKE sends=%d" % len(bot.sent))
    for chat_id, text, kwargs in bot.sent:
        print("SMOKE phrase=%r reply_to=%s" % (text, kwargs.get("reply_to_message_id")))
    assert bot.sent, "фраза не отправлена"
    assert "технически не могу" not in bot.sent[0][1].lower()
    assert "сек" in bot.sent[0][1] or "мин" in bot.sent[0][1]
    await db2.close()
    for p in (tmp, Path(str(tmp) + "-wal"), Path(str(tmp) + "-shm")):
        p.unlink(missing_ok=True)
    print("SMOKE OK")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
