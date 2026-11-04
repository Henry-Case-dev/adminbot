# -*- coding: utf-8 -*-
"""RLR-07-PROOF — R-08.20: смерть/перезапуск процесса после отправки.

Источник: `plans/owner_inputs/2026-11-05-remove-legacy-rephrasing-v2.md` §8
(строка «Смерть/перезапуск процесса после отправки → Нет повторной отправки
этого логического ответа») и карта
`plans/features/remove-legacy-rephrasing/requirements-map.json`
(R-08.20, срез RLR-07-PROOF).

Что доказывается на РЕАЛЬНОМ durable-механизме (не на моке идеального пути):

1. **Маркер пишется ДО обработки/отправки.** `direct_chat_service.handle`
   вызывает `response_freshness.mark_update_seen` (SQLite-таблица
   `smart_cache`, slug `direct_update`, TTL 24 h) сразу после захвата
   per-chat слота и ДО tool-фазы/LLM/отправки. В тесте состояние маркера
   читается реальным `check_update_seen` В МОМЕНТ отправки: если маркировку
   вернуть после отправки, проверка в `_send_direct_answer` даёт False и
   тест краснеет.
2. **Маркер переживает смерть процесса.** Кеш закрывается (как при
   завершении процесса), файл SQLite остаётся; строка маркера проверяется
   независимо через stdlib `sqlite3` — то есть это durable-запись на диске,
   а не память процесса.
3. **Повторная доставка того же `message_id` ПОСЛЕ рестарта не даёт ни
   второго LLM-ответа, ни второй отправки.** Новый процесс получает свежий
   in-memory throttle (он не переживает рестарт) — значит блокирует именно
   durable-маркер, а не остаток троттлинга.
4. **Действительно новое сообщение обрабатывается нормально** (регрессия
   «дедуп съел соседние сообщения»): новый `message_id` даёт новый ответ.

ЧЕГО ЭТОТ ФАЙЛ НЕ ДОКАЗЫВАЕТ (честная граница): реальный `systemctl restart`
на прод-хосте, kill -9 в середине записи в БД и сетевые ретраи Telegram —
это RLR-07/live-стадия. Здесь воспроизведён контракт durable-маркера на
файле SQLite и полный `DirectChatService.handle` в двух процессах-инстансах.

TEST-LIFECYCLE: CONTRACT + REGRESSION owner=RLR-07-PROOF
"""
from __future__ import annotations

import sqlite3
import time
from unittest.mock import AsyncMock

import pytest

from config.settings import Settings
from services.direct_chat_service import DirectChatService
from services.response_freshness import (
    UPDATE_DEDUP_SLUG,
    UPDATE_DEDUP_TTL_SECONDS,
    check_update_seen,
    update_dedup_key,
)
from services.smart_cache import SmartCache
from services.summary_aliases import AliasResolver
from tests.test_asap7_direct_l1 import _FakeLLM, _plan_json
from tests.test_direct_chat import (
    CHAT_ID,
    FakeDB,
    FakeMemory,
    _bot,
    _message,
    _user,
)

# Прод-дефолты гейтов (как R-08.CFG требует «реальных конфигов»): conftest
# иначе пиннит legacy-флаги OFF для немаркированных модулей.
pytestmark = [pytest.mark.system2, pytest.mark.asap3]

#: Разные тесты не должны делить один per-chat lock-ключ/чат.
TRIGGER_ID = 1301
NEW_ID = 1302


class StepLLM(_FakeLLM):
    """`_FakeLLM` + явный список стадий (доказательство «0 LLM» на повторе)."""

    def stages(self):
        return [c["step"] for c in self.calls]


def _wire(monkeypatch, *, cache, llm, l1: bool):
    """`DirectChatService` как в проде: реальный pipeline + реальный кеш-файл.

    Мокаются только I/O-края (ввод контента, отправка, реакции), как в
    существующих тестах Direct; сам маркер update-дедупа не подменяется.
    """
    import services.direct_chat_service as dcs

    monkeypatch.setattr(Settings, "DIRECT_L1_ENABLED", l1)
    monkeypatch.setattr(Settings, "PERSONA_ENABLED", False)
    svc = DirectChatService(FakeMemory(), FakeDB(), llm, AliasResolver("{}"),
                            cache=cache)
    svc._build_user_content = AsyncMock(return_value=[])
    svc._image_pre_gate_block = AsyncMock(return_value=None)
    svc._dig_pre_gate_block = AsyncMock(return_value=None)
    svc.remember_bot_reply = AsyncMock()
    monkeypatch.setattr(dcs, "react_moai", AsyncMock())
    return svc


def _instrument_send(svc, marker_probe):
    """Обёртка над ЕДИНСТВЕННЫМ швом доставки Direct-ответа.

    В момент отправки фиксирует наблюдение `marker_probe()` — так проверяется
    «маркер уже записан ДО отправки», а не «маркер когда-нибудь появится».
    """
    sends: list = []

    async def _send(bot, chat_id, answer, reply_to=None, **kwargs):
        sends.append({"chat_id": chat_id, "text": answer,
                      "reply_to": reply_to})
        marker_probe["seen_at_send"].append(await marker_probe["check"]())
        return 900 + len(sends)

    svc._send_direct_answer = AsyncMock(side_effect=_send)
    return sends


@pytest.mark.asyncio
@pytest.mark.parametrize("l1", [False, True], ids=["legacy_l1_off", "l1_on"])
async def test_no_resend_of_same_logical_answer_after_process_restart(
        tmp_path, monkeypatch, l1):
    """R-08.20: после падения/рестарта тот же update не отвечается второй раз.

    (а) маркер записан ДО отправки; (б) он durable (файл SQLite, не память);
    (в) новый процесс: тот же `message_id` → 0 LLM и 0 отправок;
    (г) новое сообщение в новом процессе обрабатывается нормально.
    """
    db_path = tmp_path / "restart_dedup.db"
    user = _user()
    key = (f"{UPDATE_DEDUP_SLUG}\x00"
           f"{update_dedup_key(CHAT_ID, TRIGGER_ID, 1, user.id)}")

    # ── ПРОЦЕСС 1: ответ доставлен, затем процесс «умирает» ─────────────────
    cache1 = SmartCache(str(db_path))
    llm1 = StepLLM(l1=_plan_json(), l2="первый и единственный ответ")
    svc1 = _wire(monkeypatch, cache=cache1, llm=llm1, l1=l1)
    probe = {"seen_at_send": [], "check": None}
    probe["check"] = lambda: check_update_seen(cache1, CHAT_ID, TRIGGER_ID,
                                              revision=1, user_id=user.id)
    sends1 = _instrument_send(svc1, probe)
    bot1 = _bot()
    msg = _message(text="сколько будет два плюс два?", message_id=TRIGGER_ID)
    try:
        await svc1.handle(bot1, msg, user)
        assert len(sends1) == 1, sends1
        # (а) На момент отправки маркер УЖЕ виден (пишется до обработки).
        assert probe["seen_at_send"] == [True]
        assert len(llm1.calls) >= 1          # ответ действительно сгенерирован
    finally:
        await cache1.close()                 # смерть процесса: соединение закрыто

    # (б) Запись durable: читаем ФАЙЛ независимым stdlib-соединением.
    with sqlite3.connect(str(db_path)) as raw:
        rows = raw.execute(
            "SELECT key, payload, created_at FROM smart_cache WHERE key = ?",
            (key,)).fetchall()
    assert len(rows) == 1, rows
    assert rows[0][1] == "1"
    # created_at ведётся по monotonic-часам smart_cache (boot-relative, общий
    # для процессов) — маркер записан только что, а не «давно истёк».
    assert abs(time.monotonic() - float(rows[0][2])) < 120

    # ── ПРОЦЕСС 2 (рестарт): свежий throttle, тот же файл, тот же update ────
    cache2 = SmartCache(str(db_path))
    llm2 = StepLLM(l1=_plan_json(), l2="второй ответ (не должен появиться)")
    svc2 = _wire(monkeypatch, cache=cache2, llm=llm2, l1=l1)
    probe2 = {"seen_at_send": [], "check": None}
    probe2["check"] = lambda: check_update_seen(cache2, CHAT_ID, TRIGGER_ID,
                                                revision=1, user_id=user.id)
    sends2 = _instrument_send(svc2, probe2)
    bot2 = _bot()
    try:
        # (в) повторная доставка того же логического события после рестарта
        await svc2.handle(bot2, _message(text="сколько будет два плюс два?",
                                         message_id=TRIGGER_ID), user)
        assert sends2 == [], "повторная отправка того же ответа"
        assert llm2.calls == [], f"второй LLM-ответ: {llm2.steps()}"
        assert bot2.send_message.await_count == 0

        # (г) действительно новое сообщение — обычная обработка.
        await svc2.handle(bot2, _message(text="а три плюс три?",
                                         message_id=NEW_ID), user)
        assert len(sends2) == 1, sends2
        if l1:
            assert llm2.stages().count("l2_writer") == 1, llm2.stages()
        else:
            assert len(llm2.calls) == 1, llm2.stages()
        assert probe2["seen_at_send"] == [True]
    finally:
        await cache2.close()


@pytest.mark.asyncio
async def test_marker_is_written_before_delivery_not_after(tmp_path,
                                                           monkeypatch):
    """R-08.20 (порядок): маркер появляется ДО отправки, не после неё.

    Если маркировку вернуть после `_send_direct_answer` (или в `finally`
    после доставки), наблюдение в момент отправки станет False — то есть
    падение процесса сразу после отправки снова давало бы дубль.
    """
    db_path = tmp_path / "order.db"
    cache = SmartCache(str(db_path))
    llm = StepLLM(l1=_plan_json(), l2="ответ по порядку")
    svc = _wire(monkeypatch, cache=cache, llm=llm, l1=True)
    user = _user()
    observed: list = []

    async def _send(bot, chat_id, answer, reply_to=None, **kwargs):
        observed.append(await check_update_seen(
            cache, chat_id, reply_to, revision=1, user_id=user.id))
        return 777

    svc._send_direct_answer = AsyncMock(side_effect=_send)
    try:
        await svc.handle(_bot(), _message(text="проверь порядок",
                                         message_id=1411), user)
        assert observed == [True], observed
    finally:
        await cache.close()


def test_update_marker_ttl_is_24_hours_and_survives_restart(tmp_path):
    """R-08.20 (срок жизни): маркер живёт 24 h и хранится на диске.

    Иначе «повторная отправка» вернулась бы через 5 минут (прежний TTL
    300 с), а рестарт процесса терял бы блокировку вовсе. Проверяются обе
    стороны: свежий маркер читается новым инстансом, а маркер старше 24 h —
    уже нет (иначе дедуп блокировал бы чат навсегда).
    """
    import asyncio

    assert UPDATE_DEDUP_TTL_SECONDS == 24 * 3600
    path = tmp_path / "ttl.db"
    key = f"{UPDATE_DEDUP_SLUG}\x00{update_dedup_key(CHAT_ID, 1501, 1, 10)}"

    async def _write():
        cache = SmartCache(str(path))
        try:
            assert cache._sweep_ttl() == 24 * 3600   # ленивая чистка не съест
            await cache.set_update_marker(
                key, "1", ttl_seconds=UPDATE_DEDUP_TTL_SECONDS)
        finally:
            await cache.close()

    async def _read(ttl):
        cache = SmartCache(str(path))
        try:
            return await cache.get_update_marker(key, ttl_seconds=ttl)
        finally:
            await cache.close()

    asyncio.run(_write())
    # (1) Новый инстанс (рестарт процесса) видит маркер в пределах 24 h.
    assert asyncio.run(_read(UPDATE_DEDUP_TTL_SECONDS)) == "1"

    # (2) Маркер старше 24 h больше не блокирует (TTL реально применяется).
    with sqlite3.connect(str(path)) as raw:
        raw.execute("UPDATE smart_cache SET created_at = created_at - ? "
                    "WHERE key = ?",
                    (UPDATE_DEDUP_TTL_SECONDS + 3600, key))
        raw.commit()
    assert asyncio.run(_read(UPDATE_DEDUP_TTL_SECONDS)) is None
