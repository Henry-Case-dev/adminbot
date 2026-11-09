"""MOD-ACL-UX-01 M2 — CHAT OFF в полёте (ТЗ §2.5, строки MAC-S2-113/114/115,
MAC-S10-07, MAC-S10-20).

Проверяется НАБЛЮДАЕМЫЙ результат, а не число вызовов мока:

1. задание, созданное при ON, но чей чат выключили во время работы, НЕ
   публикует результат (ровно один терминальный исход, ноль доставок);
2. уже сгенерированный результат не уходит в отключённый чат второй раз и не
   откладывается «на потом» (повторное включение не даёт replay/backfill);
3. сохранённые данные (переписка, журнал попыток, настройка чата) остаются
   нетронутыми;
4. отложенный результат (deferred meme / durable intent) проверяется СВЕЖИМ
   профилем перед отправкой.

TEST-LIFECYCLE: CONTRACT owner=MOD-ACL-UX-01 §2.5 (M2)
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest

from services import chat_params, hot_config, mca_events
from services import initiative_observer as obs

CHAT = -2031
CHAT_B = -2032
BOT_ID = 999
NOW = datetime(2026, 11, 9, 12, 0, tzinfo=timezone.utc)


# ── общая инфраструктура (минимальная, без сети/Telegram) ────────────────────

class _MutableChatParams:
    """Per-chat root с возможностью «выключить чат в полёте».

    ``by_chat`` хранит САМИ overrides (как и написано в фикстурах ниже):
    `{"initiative.frequency_profile": "active", ...}`.
    """

    def __init__(self, by_chat=None):
        self.by_chat = {int(k): dict(v) for k, v in (by_chat or {}).items()}

    async def get_chat_params(self, chat_id):
        data = self.by_chat.get(int(chat_id), {})
        return {"overrides": dict(data), "gates": {}}

    async def get_chat_params_full(self, chat_id):
        return await self.get_chat_params(chat_id), None

    def disable(self, chat_id):
        self.by_chat.setdefault(int(chat_id), {})["initiative.enabled"] = False

    def enable(self, chat_id):
        self.by_chat.setdefault(int(chat_id), {})["initiative.enabled"] = True


class _FakeHot:
    def __init__(self, values=None):
        self.values = dict(values or {})

    def get(self, key, default=None):
        return self.values.get(key, default)


def _set_caches(by_chat):
    hot_config.set_config_cache(_FakeHot({}))
    cache = _MutableChatParams(by_chat)
    chat_params.set_chat_params_cache(cache)
    return cache


@pytest.fixture(autouse=True)
def _clean_state():
    mca_events.reset_pending()
    yield
    mca_events.reset_pending()
    chat_params.set_chat_params_cache(None)
    hot_config.set_config_cache(None)


@pytest.fixture(autouse=True)
def _no_exploration_draw(monkeypatch):
    """Детерминизм: exploration-розыгрыш выключен.

    Иначе probability-политика иногда выбирает другую форму участия
    (silent вместо reply), и тест мерил бы не «OFF в полёте», а случайный
    выбор. Гейт/резолвер от этого не зависит.
    """
    import services.mca_exploration as expl

    async def _off(db, purpose, chat_id):
        return False, "test_disabled"

    monkeypatch.setattr(expl, "exploration_allowed", _off)


class _FakeBot:
    def __init__(self):
        self.id = BOT_ID
        self.sent: list = []

    async def send_message(self, chat_id, text, **kwargs):
        self.sent.append((int(chat_id), text))

        class _Msg:
            message_id = 7000 + len(self.sent)

        return _Msg()


class _FakeWriter:
    """Duck-typed DirectChatService (контракт §13.2)."""

    def __init__(self, action="reply", text="Продолжим тему?"):
        self.action = action
        self.text = text
        self.plan_calls = 0
        self.generate_calls = 0

    async def plan_initiative_decision(self, chat_id, intent_row, *,
                                       correlation_id=None):
        from services.direct_l1 import L1Plan
        self.plan_calls += 1
        return L1Plan(action=self.action, confidence=0.9,
                      confidence_bucket="high", source="llm")

    async def generate_initiative_reply(self, chat_id, intent_row, *,
                                        l1_plan=None, correlation_id=None):
        self.generate_calls += 1
        return self.text


class _FlippingLLM:
    """Оценщик наблюдателя: возвращает opportunity и «выключает чат» в полёте.

    Свитч происходит МЕЖДУ созданием задания (проверка чата пройдена) и
    первым пользовательским side effect — ровно сценарий §2.5.
    """

    def __init__(self, cache, chat_id, verdict):
        self.cache = cache
        self.chat_id = int(chat_id)
        self.verdict = verdict
        self.calls = 0

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.cache.disable(self.chat_id)
        return self.verdict


_ACTIVE = {
    "initiative.frequency_profile": "active",
    "initiative.eval_min_messages": 4,
    "initiative.eval_min_interval_seconds": 0,
    "initiative.min_gap_seconds": 0,
    "initiative.max_replies_per_day": 10,
    "initiative.eval_llm_budget_per_day": 10,
}


def _verdict(**kw) -> str:
    base = {"opportunity": True, "kind": "development", "action": "say",
            "horizon": "now", "addressee_user_id": None,
            "topic_key": "games", "goal": "участники обсуждают игры",
            "rationale": "живая тема"}
    base.update(kw)
    return json.dumps(base, ensure_ascii=False)


async def _db(tmp_path, name):
    from services.database import DatabaseService
    d = DatabaseService(str(tmp_path / name))
    await d.initialize()
    return d


async def _msg(db, *, chat_id=CHAT, user_id=42, text, ts=None):
    ts = int(time.time()) if ts is None else int(ts)
    cursor = await db.db.execute(
        "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
        "timestamp, media_type, author_name, is_forward, tg_message_id) "
        "VALUES (?, ?, ?, NULL, ?, 'text', 'u', 0, NULL)",
        (user_id, chat_id, text, ts))
    await db.db.commit()
    return cursor.lastrowid


async def _payload_of(db):
    cursor = await db.db.execute(
        "SELECT payload FROM task_jobs WHERE kind = ? "
        "ORDER BY finished_at DESC, created_at DESC, rowid DESC LIMIT 1",
        (obs.OBSERVE_JOB_KIND,))
    row = await cursor.fetchone()
    return json.loads(row["payload"] or "{}")


def _emitted(event_name: str, *, chat_id=None):
    """Событие из bounded in-memory журнала mca_events (не мок вызова)."""
    out = []
    for item in list(mca_events._pending):
        if str(item.get("event_name") or "") != event_name:
            continue
        if chat_id is not None and int(item.get("chat_id") or 0) != int(chat_id):
            continue
        out.append(item)
    return out


# ═══ текстовая инициатива: OFF в полёте ═════════════════════════════════════

@pytest.mark.asyncio
async def test_text_initiative_off_mid_flight_single_outcome(tmp_path):
    """MAC-S2-113/114 + MAC-S10-07: чат выключили во время оценки/генерации.

    Ожидаем ровно один терминальный исход: ноль доставок, ноль событий
    `initiative_sent`, одно `initiative_publication_cancelled` с машинной
    причиной, сохранённые данные и сама настройка чата не переписаны.
    """
    db = await _db(tmp_path, "inflight_text.db")
    cache = _set_caches({CHAT: dict(_ACTIVE)})
    bot, writer = _FakeBot(), _FakeWriter()
    try:
        base = int(time.time()) - 3600
        for i in range(6):
            await _msg(db, user_id=42 + i % 2, text=f"живая тема {i}",
                       ts=base + i)
        before = await db.db.execute(
            "SELECT COUNT(*) AS n FROM smart_messages WHERE chat_id = ?",
            (CHAT,))
        msg_count_before = int((await before.fetchone())["n"])

        llm = _FlippingLLM(cache, CHAT, _verdict())
        status = await obs.observe_tick(db, bot=bot, writer_service=writer,
                                        llm=llm)
        assert status == "completed"

        # 1) публикации нет — ни одного сообщения в выключенный чат
        assert bot.sent == []
        assert _emitted("initiative_sent", chat_id=CHAT) == []
        # 2) текст сгенерирован ОДИН раз (дубля результата нет)
        assert writer.generate_calls == 1
        payload = await _payload_of(db)
        assert payload["counters"]["sent"] == 0
        assert payload["counters"].get("capability_blocked") == 1
        # 3) один терминальный исход с машинной причиной
        cancelled = _emitted("initiative_publication_cancelled", chat_id=CHAT)
        assert len(cancelled) == 1
        assert cancelled[0]["reason_code"] == "capability_off"
        assert cancelled[0]["stage"] == "capability:off"
        # 4) сохранённые данные и настройка чата не тронуты
        after = await db.db.execute(
            "SELECT COUNT(*) AS n FROM smart_messages WHERE chat_id = ?",
            (CHAT,))
        assert int((await after.fetchone())["n"]) == msg_count_before
        assert cache.by_chat[CHAT]["initiative.enabled"] is False
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_text_initiative_no_replay_after_reenable(tmp_path):
    """MAC-S2-115: повторное включение не даёт replay/backfill.

    Первый проход отменил публикацию из-за OFF (результат не сохранён как
    «отложенный»), второй — уже при ON и без новых сообщений — не
    пере-оценивает окно и ничего не отправляет: курсор/дедуп двигаются
    штатно, массовой догрузки нет.
    """
    db = await _db(tmp_path, "inflight_replay.db")
    cache = _set_caches({CHAT: dict(_ACTIVE)})
    bot, writer = _FakeBot(), _FakeWriter()
    try:
        base = int(time.time()) - 3600
        for i in range(6):
            await _msg(db, user_id=42 + i % 2, text=f"тема повтора {i}",
                       ts=base + i)
        llm = _FlippingLLM(cache, CHAT, _verdict())
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        assert bot.sent == [] and llm.calls == 1

        # Владелец включает чат обратно — сообщений НЕ добавилось.
        cache.enable(CHAT)
        assert await obs.observe_tick(db, bot=bot, writer_service=writer,
                                      llm=llm) == "completed"
        # Ни новой оценки (окно уже оценено), ни «догоняющей» публикации.
        assert llm.calls == 1
        assert bot.sent == []
        assert _emitted("initiative_sent", chat_id=CHAT) == []
    finally:
        await db.close()


# ═══ мем-ветка: OFF в полёте ════════════════════════════════════════════════

def _meme_ledger(tmp_path):
    from services import meme_initiative as meme
    led = meme.SqliteQuotaLedger(str(tmp_path / "meme-inflight.db"))
    led.apply_schema()
    return led


def _meme_rows(chat_id: int, n: int = 3):
    return [{"chat_id": chat_id, "id": i, "text": f"реплика {i}"}
            for i in range(n)]


class _MemeProvider:
    """Провайдер изображения, который «выключает чат» во время генерации."""

    def __init__(self, cache, chat_id):
        self.cache = cache
        self.chat_id = int(chat_id)
        self.calls = []

    async def __call__(self, prompt, chat_id, job_id):
        self.calls.append(int(chat_id))
        self.cache.disable(self.chat_id)
        return SimpleNamespace(ok=True, called=True, reason="", content=b"png")


@pytest.mark.asyncio
async def test_meme_off_mid_flight_cancels_publication(tmp_path):
    """MAC-S2-113/S10-07: картинка готова, но чат выключили — публикации нет.

    Проверяется сохранённый итог: одно терминальное состояние попытки
    (published=False, generated=True), ноль вызовов отправителя, одна строка
    журнала попытки и отсутствие отложенного мема (иначе повторное включение
    «догрузило» бы старый результат — MAC-S2-115).
    """
    from services import meme_initiative as meme
    from services.database import DatabaseService

    svc = DatabaseService(str(tmp_path / "meme_inflight.db"))
    await svc.initialize()
    cache = _set_caches({})
    ledger = _meme_ledger(tmp_path)
    provider = _MemeProvider(cache, -100)
    sent: list = []

    async def sender(chat_id, content, prompt):
        sent.append(int(chat_id))
        return SimpleNamespace(message_id=1)

    async def summarizer(cid, rows, system):
        return "хук"

    async def joke_generator(cid, summary, instruction):
        return "прикол"

    async def chat_enabled(cid):
        return not (cache.by_chat.get(int(cid), {}).get(
            "initiative.enabled") is False)

    try:
        result = await meme.consider_chat(
            svc, -100,
            settings=meme.MemeSettings(
                enabled=True, window_messages=8, daily_limit=3,
                cooldown_seconds=0, min_messages=1, trigger_probability=1.0),
            ledger=ledger, now=NOW, tz_name="UTC",
            tz_source="utc_fallback", initiative_enabled=lambda: True,
            chat_enabled=chat_enabled,
            image_status={"available": True, "reason": "ok",
                          "health": "healthy", "configured": True,
                          "module_enabled": True},
            image_provider=provider, messages=_meme_rows(-100),
            summarizer=summarizer, joke_generator=joke_generator,
            model_chars=200, sender=sender)

        assert provider.calls == [-100]          # генерация была ровно одна
        assert sent == []                        # публикации нет
        assert result.published is False
        assert result.generated is True
        assert result.reason == meme.SKIP_INITIATIVE_DISABLED
        # Никакого «отложенного на потом» результата (нет replay при ON).
        assert await meme.deferred_active_row(svc, -100) is None
        # Журнал попытки: ровно одна терминальная строка этой попытки
        # (журнал живёт в файле квоты-леджера, не в БД чата).
        import sqlite3
        conn = sqlite3.connect(ledger.path)
        try:
            conn.row_factory = sqlite3.Row
            rows = [dict(row) for row in conn.execute(
                f"SELECT stage, outcome, reason_code FROM {meme.ATTEMPT_TABLE} "
                "WHERE chat_id = ? AND reason_code = ?",
                (-100, meme.SKIP_INITIATIVE_DISABLED))]
        finally:
            conn.close()
        assert len(rows) == 1
        assert rows[0]["stage"] == meme.STAGE_PUBLISH
        assert rows[0]["outcome"] == "skipped"
    finally:
        await svc.close()


@pytest.mark.asyncio
async def test_deferred_meme_not_published_after_chat_off(tmp_path, monkeypatch):
    """MAC-S10-20/S2-115: отложенный результат НЕ публикуется в отключённый чат.

    Строка отложенного мема уже есть (задача запрошена до выключения).
    Доставка при OFF обязана закрыть её терминально без отправки, а не
    «подождать включения»: иначе включение вызвало бы неконтролируемый
    replay. Байты результата удаляются вместе с терминальной строкой.
    """
    from services import meme_initiative as meme
    from services.database import DatabaseService

    monkeypatch.setenv("MEME_PENDING_DIR", str(tmp_path / "pending"))
    svc = DatabaseService(str(tmp_path / "meme_deferred.db"))
    await svc.initialize()
    cache = _set_caches({})
    ledger = _meme_ledger(tmp_path)
    sent: list = []

    async def sender(chat_id, content, prompt):
        sent.append(int(chat_id))
        return SimpleNamespace(message_id=1)

    async def chat_enabled(cid):
        return not (cache.by_chat.get(int(cid), {}).get(
            "initiative.enabled") is False)

    try:
        ok = await meme.defer_generated_meme(
            svc, chat_id=-100, content=b"png-bytes",
            snapshot=meme.SourceSnapshot(
                chat_id=-100, run_id="job-off", mode=meme.MODE_AUTOMATIC,
                purpose=meme.PURPOSE_AUTOMATIC, request_ref="job-off",
                message_ids=(1,), message_count=1, first_id=1, last_id=1,
                digest="d", captured_at=int(NOW.timestamp())),
            run_id="job-off", reason=meme.SKIP_PUBLICATION_IN_FLIGHT,
            detail="seed", cfg=meme.MemeSettings(enabled=True),
            prompt_origin="factory", now_ts=int(NOW.timestamp()))
        assert ok and ok.get("job_id")
        job_id = str(ok["job_id"])
        artifact = str(ok["path"])

        cache.disable(-100)
        result = await meme.deliver_deferred(
            svc, -100, ledger=ledger, sender=sender,
            chat_enabled=chat_enabled, initiative_enabled=lambda: True,
            settings=meme.MemeSettings(enabled=True),
            now=NOW, now_ts=int(NOW.timestamp()) + 5,
            tz_name="UTC", tz_source="utc_fallback")

        assert sent == []
        assert result is not None and result.published is False
        assert result.reason == meme.SKIP_INITIATIVE_DISABLED
        assert await meme.deferred_active_row(svc, -100) is None
        # Артефакт не остался «висеть»: терминальное закрытие убрало байты.
        assert meme.load_deferred_bytes({"result_ref": artifact}) is None
        import os
        assert not os.path.exists(artifact)
        assert job_id
    finally:
        await svc.close()


# ═══ единая точка «можно ли публиковать» ════════════════════════════════════

@pytest.mark.asyncio
async def test_publish_block_reason_reads_fresh_profile():
    """Финальная проверка видит OFF, даже если TTL-кэш ещё держит ON.

    Это и есть «OFF из устаревшего snapshot» (§2.5): свежее чтение профиля
    обходит TTL, а не полагается на прогретый кэш.
    """
    class _PgConn:
        def __init__(self):
            self.chat_params = {"v": 1, "overrides": {"initiative.enabled": False}}
            self.updated_at = "2026-11-09T10:00:00+00:00"

        async def fetchrow(self, sql, *args):
            return {"chat_id": args[0], "updated_at": self.updated_at,
                    "chat_params": self.chat_params, "gates_opt_in": False}

    class _Pool:
        def __init__(self, conn):
            self.conn = conn

        def acquire(self):
            conn = self.conn

            class _CM:
                async def __aenter__(self):
                    return conn

                async def __aexit__(self, *exc):
                    return False
            return _CM()

    class _Pg:
        def __init__(self, conn):
            self.pool = _Pool(conn)

    conn = _PgConn()
    cache = chat_params.ChatParamsCache(_Pg(conn))
    # «Прогретый» кэш держит ON (устаревший снимок)…
    cache._items[CHAT] = (time.monotonic(), {"overrides": {
        "initiative.enabled": True}}, "old")
    chat_params.set_chat_params_cache(cache)
    hot_config.set_config_cache(_FakeHot({}))
    try:
        # …но финальная проверка читает профиль и видит OFF.
        assert await obs.chat_observer_enabled(CHAT) is True
        reason = await obs.initiative_publish_block_reason(CHAT)
        assert reason == "capability_off"
        # После инвалидации обе поверхности согласованы.
        await chat_params.invalidate_chat_from_notify(CHAT)
        assert await obs.chat_observer_enabled(CHAT) is False
    finally:
        chat_params.set_chat_params_cache(None)
        hot_config.set_config_cache(None)
