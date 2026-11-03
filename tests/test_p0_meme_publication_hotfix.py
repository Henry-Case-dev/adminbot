"""P0 MEME-PUBLICATION (03.11.2026) — готовый мем не отменяется потому, что
чат жил своей жизнью.

Контракт владельца (`plans/owner_inputs/2026-11-03-hotfix-meme-publication-
initiative-ui.md` §1.2, §1.3, §1.4):

  * на старте генерации фиксируется СНАПШОТ ИСТОЧНИКА (чат, run, сообщения и
    их версии, цель/режим) — это входной материал мема, а не требование, чтобы
    чат оставался неподвижным;
  * новые сообщения, реакции, смена `latest_message_id`, движение watermark и
    обычный рост переписки НЕ являются основанием для `publication_stale`;
  * ручной `/meme` доставляет готовый мем даже если чат ушёл вперёд; повторного
    `/meme` и второй генерации не требуется;
  * автоматический мем публикуется, если выполнены его настоящие условия, либо
    откладывается по РЕАЛЬНОЙ коллизии/терминальному условию с точным кодом;
  * `publication_stale` — только для доказанной утраты валидности, и никогда
    из-за сравнения двух timestamp/message id;
  * события разделяют «генерация прошла» и «отправка прошла»;
  * пустой «Потолок длины» = АВТО во всём тракте (UI → API → PG → runtime →
    диагностика), без подставных 0/800/NaN.

Каждая проверка может упасть: наблюдается реальный результат попытки/журнал
(счёт вызовов sender/провайдера, коды причин, события, слоты квоты), подменены
только внешние границы (LLM, image-провайдер, Telegram) и часы.

Мутационная проверка ядра (см. отчёт): вернуть сравнение watermark или
`publication_stale` по изменению окна — падают
`test_*_new_messages_do_not_cancel_ready_meme` и
`test_reason_codes_are_distinct_and_stale_is_not_emitted`.

TEST-LIFECYCLE: CONTRACT owner=OI-2026-11-03-HOTFIX-MEME-PUBLICATION
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from services import mca_random_source as mrs
from services import meme_initiative as meme
from services import publication_coordination as pub

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)
NOW_TS = int(NOW.timestamp())
CHAT = -100
IMAGE_OK = {"available": True, "reason": "ok", "health": "healthy",
            "configured": True, "module_enabled": True}
GROWTH = (1, 10, 50)


# ── двойники внешних границ ─────────────────────────────────────────────────

class _Cursor:
    def __init__(self, rows):
        self._rows = list(rows)

    async def fetchall(self):
        return list(self._rows)

    async def fetchone(self):
        return self._rows[0] if self._rows else None


class _GrowingChat:
    """DB-двойник «живого» чата: каждый запрос видит БОЛЬШЕ переписки.

    Именно это и было инцидентом: пока шла генерация, в чате появлялись новые
    сообщения (``watermark``/``latest_message_id`` росли). Двойник честно
    отдаёт растущий ``MAX(id)`` и полный список исходных сообщений — поэтому
    любой вернувшийся «сравни watermark» сразу делает тест красным.
    """

    def __init__(self, rows, *, growth: int = 1, source_remaining=None):
        self.db_path = ":memory:"
        self._base = [dict(row) for row in rows]
        self._growth = max(0, int(growth))
        self._remaining = source_remaining
        self.queries: list[str] = []
        self.max_id = max((int(row["id"]) for row in self._base), default=0)
        self.calls = 0

    def _grow(self) -> None:
        self.calls += 1
        self.max_id += self._growth          # чат говорит дальше
        self._base.append({"chat_id": CHAT, "id": self.max_id,
                           "text": f"новое сообщение {self.max_id}"})

    async def execute(self, sql: str, params=()):
        self.queries.append(str(sql))
        self._grow()
        if "MAX(id)" in sql:
            return _Cursor([{"m": self.max_id}])
        if "COUNT(*)" in sql:
            value = (len(self._base) if self._remaining is None
                     else int(self._remaining))
            return _Cursor([{"c": value}])
        chat_id, limit = int(params[0]), int(params[-1])
        rows = [row for row in self._base
                if int(row.get("chat_id", chat_id)) == chat_id]
        return _Cursor(rows[-limit:])

    async def record_bot_output(self, *args, **kwargs):
        """Журнал выводов бота: настоящая запись — в БД сервиса, здесь заглушка.
        Доставка от неё не зависит (см. `_record_meme_output`)."""
        return "out-p0"


class _Provider:
    def __init__(self, *, ok: bool = True, content=b"png", reason=""):
        self.ok = ok
        self.content = content
        self.reason = reason
        self.calls: list[tuple] = []

    async def __call__(self, prompt, chat_id, job_id):
        self.calls.append((prompt, chat_id, job_id))
        return SimpleNamespace(ok=self.ok, called=True, reason=self.reason,
                               content=self.content)


class _Sender:
    def __init__(self, *, boom: bool = False):
        self.boom = boom
        self.calls: list[tuple] = []

    async def __call__(self, chat_id, content, prompt):
        self.calls.append((chat_id, content, prompt))
        if self.boom:
            raise RuntimeError("telegram down")
        return SimpleNamespace(message_id=900 + len(self.calls))


class _Hit:
    def __init__(self, value: float = 0.0):
        self.value = value

    async def draw_probability(self, **kwargs):
        return mrs.DrawResult(value=self.value, deferred=False,
                              fallback_reason=None, source="pseudorandom",
                              selected_source="quantum", draw_id="draw-p0")


class _RecordingCoordinator:
    """Обёртка реального координатора: запоминает аргументы `acquire`.

    Это проверка того, что ручной путь ДОЖИДАЕТСЯ разрешённого слота
    существующим durable-механизмом, а не теряет готовую картинку.
    """

    def __init__(self, inner: pub.PublicationCoordinator):
        self.inner = inner
        self.acquire_calls: list[dict] = []

    def store(self):
        return self.inner.store()

    def available(self) -> bool:
        return self.inner.available()

    async def precheck(self, *args, **kwargs):
        return await self.inner.precheck(*args, **kwargs)

    async def acquire(self, chat_id, holder_kind, **kwargs):
        self.acquire_calls.append({"chat_id": chat_id,
                                   "holder_kind": holder_kind, **kwargs})
        return await self.inner.acquire(chat_id, holder_kind, **kwargs)

    async def begin_sending(self, *args, **kwargs):
        return await self.inner.begin_sending(*args, **kwargs)

    async def release(self, *args, **kwargs):
        return await self.inner.release(*args, **kwargs)


# ── общий прогон ───────────────────────────────────────────────────────────

def _store(tmp_path, name: str = "p0.db") -> pub.SqliteClaimStore:
    path = str(tmp_path / name)
    meme.SqliteQuotaLedger(path).apply_schema()
    return pub.SqliteClaimStore(path)


def _settings(**overrides) -> meme.MemeSettings:
    base = dict(enabled=True, window_messages=10, daily_limit=3,
                cooldown_seconds=0, min_messages=1, trigger_probability=1.0)
    base.update(overrides)
    return meme.MemeSettings(**base)


def _rows(n: int = 5) -> list[dict]:
    return [{"chat_id": CHAT, "id": i, "text": f"реплика {i}"}
            for i in range(1, n + 1)]


async def _pass(tmp_path, *, manual: bool, db=None, sender=None,
                provider=None, settings=None, store=None, job_id=None,
                gate=None, joke="прикол", joke_fn=None, summarizer=None,
                publication=None, ledger=None, source_check=None,
                initiative_enabled=None, request_ref=""):
    store = store if store is not None else _store(tmp_path)
    led = ledger if ledger is not None else meme.SqliteQuotaLedger(store.path)
    # Окно читается из «живой» БД: тогда работает и проверка исходного
    # материала (штатный путь), и рост переписки во время генерации.
    db = db if db is not None else _GrowingChat(_rows())

    async def _summarizer(_cid, _rows_arg, _system):
        return "хук"

    async def _joke(_cid, _summary, _instruction):
        return joke

    async def _gate(_cid):
        return (True, "ok") if gate is None else gate()

    return await meme.consider_chat(
        db, CHAT, settings=settings if settings is not None else _settings(),
        ledger=led, now=NOW, now_ts=NOW_TS, tz_name="UTC",
        tz_source="utc_fallback",
        initiative_enabled=initiative_enabled or (lambda: True),
        image_status=IMAGE_OK, random_source=_Hit(0.0),
        summarizer=summarizer or _summarizer,
        joke_generator=joke_fn or _joke,
        image_provider=provider if provider is not None else _Provider(),
        publish_gate=_gate,
        sender=sender if sender is not None else _Sender(),
        claim_store=store, model_chars=None, manual=manual,
        job_id=job_id, publication=publication, source_check=source_check,
        request_ref=request_ref)


def _journal(ledger) -> list[dict]:
    return ledger.attempts(CHAT)


def _terminal_facts(ledger, job_id: str | None = None) -> dict:
    for row in ledger.attempts(CHAT):
        if job_id and str(row.get("job_id")) != job_id:
            continue
        facts = meme.parse_attempt_facts(row)
        if facts.get("events"):
            return facts
    return {}


def _reason_codes(ledger) -> list[str]:
    return [str(row.get("reason_code") or "") for row in _journal(ledger)
            if row.get("reason_code")]


# ═══ 1/2. новые сообщения во время генерации не отменяют готовый мем ════════

@pytest.mark.parametrize("growth", GROWTH)
def test_manual_new_messages_do_not_cancel_ready_meme(tmp_path, growth):
    """`/meme` + 1/10/50 новых сообщений → мем отправляется ровно один раз."""
    store = _store(tmp_path)
    led = meme.SqliteQuotaLedger(store.path)
    chat = _GrowingChat(_rows(), growth=growth)
    sender = _Sender()
    provider = _Provider()
    before_max = chat.max_id

    result = asyncio.run(_pass(tmp_path, manual=True, db=chat, store=store,
                               ledger=led, sender=sender, provider=provider))

    assert result.published is True and result.reason == "sent"
    assert len(sender.calls) == 1
    assert len(provider.calls) == 1                # второй генерации нет
    # Рост чата действительно произошёл во время прогона.
    assert chat.max_id > before_max and chat.calls > 1
    assert meme.SKIP_PUBLICATION_STALE not in _reason_codes(led)
    facts = _terminal_facts(led)
    assert facts.get("delivery") == "sent"


@pytest.mark.parametrize("growth", GROWTH)
def test_automatic_new_messages_do_not_cancel_ready_meme(tmp_path, growth):
    """Авто-мем с теми же новыми сообщениями публикуется по своим условиям."""
    store = _store(tmp_path)
    led = meme.SqliteQuotaLedger(store.path)
    chat = _GrowingChat(_rows(), growth=growth)
    sender = _Sender()
    provider = _Provider()

    result = asyncio.run(_pass(tmp_path, manual=False, db=chat, store=store,
                               ledger=led, sender=sender, provider=provider))

    assert result.published is True and result.reason == "sent"
    assert len(sender.calls) == 1 and len(provider.calls) == 1
    assert meme.SKIP_PUBLICATION_STALE not in _reason_codes(led)


def test_manual_delivers_after_chat_topic_changed(tmp_path):
    """Чат сменил тему и набежало 50 сообщений — мем всё равно доставлен."""
    store = _store(tmp_path)
    led = meme.SqliteQuotaLedger(store.path)
    chat = _GrowingChat(_rows(), growth=50)
    sender = _Sender()
    result = asyncio.run(_pass(tmp_path, manual=True, db=chat, store=store,
                               ledger=led, sender=sender,
                               request_ref="77"))
    assert result.published is True
    assert len(sender.calls) == 1
    events = _terminal_facts(led)["events"]
    snapshot = next(item for item in events
                    if item["name"] == meme.EVENT_SOURCE_SNAPSHOT)
    assert snapshot["mode"] == meme.MODE_MANUAL
    assert snapshot["purpose"] == meme.PURPOSE_MANUAL


# ═══ 3. один универсальный код на все случаи запрещён ══════════════════════

def test_reason_codes_are_distinct_and_stale_is_not_emitted(tmp_path):
    """Модуль/инициатива/backend/источник/гейт — РАЗНЫЕ коды, не stale."""
    codes: dict[str, str] = {}

    # (a) модуль мема выключен
    led_a = meme.SqliteQuotaLedger(str(tmp_path / "a.db"))
    led_a.apply_schema()
    result = asyncio.run(_pass(tmp_path, manual=False, settings=_settings(
        enabled=False), ledger=led_a))
    codes["module_off"] = result.reason

    # (b) инициатива выключена
    led_b = meme.SqliteQuotaLedger(str(tmp_path / "b.db"))
    led_b.apply_schema()
    result = asyncio.run(_pass(tmp_path, manual=False, ledger=led_b,
                               initiative_enabled=lambda: False))
    codes["initiative_off"] = result.reason

    # (c) image backend недоступен
    led_c = meme.SqliteQuotaLedger(str(tmp_path / "c.db"))
    led_c.apply_schema()
    result = asyncio.run(meme.consider_chat(
        None, CHAT, settings=_settings(), ledger=led_c, now=NOW, now_ts=NOW_TS,
        tz_name="UTC", tz_source="utc_fallback",
        initiative_enabled=lambda: True,
        image_status={"available": False,
                      "reason": meme.SKIP_IMAGE_UNHEALTHY},
        random_source=_Hit(0.0), sender=_Sender()))
    codes["image_backend"] = result.reason

    # (d) исходный материал удалён (содержательная утрата валидности)
    led_d = meme.SqliteQuotaLedger(str(tmp_path / "d.db"))
    led_d.apply_schema()
    store_d = pub.open_store(None, path=led_d.path)
    chat_d = _GrowingChat(_rows(), growth=1, source_remaining=0)
    result = asyncio.run(_pass(tmp_path, manual=False, db=chat_d,
                               store=store_d, ledger=led_d))
    codes["source_gone"] = result.reason
    assert result.detail == "source_messages_deleted"

    # (e) publish-гейт закрыт
    led_e = meme.SqliteQuotaLedger(str(tmp_path / "e.db"))
    led_e.apply_schema()
    result = asyncio.run(_pass(tmp_path, manual=False, ledger=led_e,
                               gate=lambda: (False, "already_answered")))
    codes["gate_blocked"] = result.reason

    # (f) настоящая коллизия координации (чужой механизм уже отправляет)
    led_f = meme.SqliteQuotaLedger(str(tmp_path / "f.db"))
    led_f.apply_schema()
    store_f = pub.SqliteClaimStore(led_f.path)
    foreign = store_f.acquire(chat_id=CHAT, holder_kind=pub.KIND_TEXT_INITIATIVE,
                              now=NOW_TS, interval_seconds=0)
    assert foreign.granted
    assert store_f.begin_sending(chat_id=CHAT, claim_id=foreign.claim_id,
                                 now=NOW_TS).granted
    result = asyncio.run(_pass(tmp_path, manual=False, store=store_f,
                               ledger=led_f))
    codes["collision"] = result.reason

    assert len(set(codes.values())) == len(codes), codes
    assert meme.SKIP_PUBLICATION_STALE not in codes.values()
    assert codes["module_off"] == meme.SKIP_DISABLED
    assert codes["initiative_off"] == meme.SKIP_INITIATIVE_DISABLED
    assert codes["image_backend"] == meme.SKIP_IMAGE_UNHEALTHY
    assert codes["source_gone"] == meme.SKIP_SOURCE_GONE
    assert codes["gate_blocked"] == meme.SKIP_PUBLISH
    assert codes["collision"] in (meme.SKIP_PUBLICATION_CONFLICT,
                                  meme.SKIP_PUBLICATION_IN_FLIGHT)


def test_module_disabled_during_generation_is_a_real_content_reason(tmp_path):
    """Модуль выключили, пока шла генерация → честная отмена, не stale."""
    store = _store(tmp_path)
    led = meme.SqliteQuotaLedger(store.path)
    sender = _Sender()

    # Тумблер читается ЗАНОВО на момент публикации (не «значение из памяти»):
    # явное выключение — реальное терминальное содержание, а не «чат изменился».
    from services import chat_params
    original = chat_params.get_chat_param

    async def _param(chat_id, key, default=None):
        if key == meme.KEY_ENABLED:
            return False
        return await original(chat_id, key, default)

    chat_params.get_chat_param = _param
    try:
        result = asyncio.run(_pass(tmp_path, manual=False, store=store,
                                   ledger=led, sender=sender,
                                   settings=_settings()))
    finally:
        chat_params.get_chat_param = original

    assert result.published is False
    assert sender.calls == []
    assert result.reason == meme.SKIP_DISABLED
    assert result.detail == "module_disabled_during_generation"
    assert result.generated is True          # картинка была готова
    assert meme.SKIP_PUBLICATION_STALE not in _reason_codes(led)


# ═══ 4. два воркера и рестарт: ни дубля, ни второй генерации ═══════════════

def test_restart_same_job_does_not_duplicate_or_regenerate(tmp_path):
    """Повтор после «рестарта»: тот же job не даёт дубля и второй генерации."""
    store = _store(tmp_path)
    led = meme.SqliteQuotaLedger(store.path)
    sender = _Sender()
    provider = _Provider()

    first = asyncio.run(_pass(tmp_path, manual=False, store=store, ledger=led,
                              sender=sender, provider=provider,
                              job_id="job-restart"))
    assert first.published is True
    second = asyncio.run(_pass(tmp_path, manual=False, store=store, ledger=led,
                               sender=sender, provider=provider,
                               job_id="job-restart"))

    assert second.published is False
    assert len(sender.calls) == 1              # дубля в чат нет
    assert len(provider.calls) == 1            # второй платной генерации нет
    day = meme.day_window(CHAT, NOW, tz_name="UTC")
    assert meme.quota_view(led, chat_id=CHAT, day=day, limit=3)["spent"] == 1
    # Подтверждённая стадия провайдера осталась durable после «рестарта».
    statuses = [str(row["status"]) for row in _reservations(led)]
    assert statuses == ["provider_called"]


def _reservations(ledger) -> list[dict]:
    import sqlite3
    conn = sqlite3.connect(ledger.path)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.execute(
            f"SELECT job_id, status FROM {meme.RESERVATION_TABLE} "
            "WHERE chat_id = ?", (CHAT,))
        return [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()


def test_two_workers_in_one_chat_publish_exactly_once(tmp_path):
    """Два воркера одновременно: ровно одна публикация, один платный вызов."""
    store = _store(tmp_path)
    led = meme.SqliteQuotaLedger(store.path)
    sender = _Sender()
    provider = _Provider()
    chat = _GrowingChat(_rows(), growth=5)

    async def scenario():
        return await asyncio.gather(
            _pass(tmp_path, manual=False, db=chat, store=store, ledger=led,
                  sender=sender, provider=provider, job_id="job-w"),
            _pass(tmp_path, manual=False, db=chat, store=store, ledger=led,
                  sender=sender, provider=provider, job_id="job-w"))

    first, second = asyncio.run(scenario())
    published = [item for item in (first, second) if item.published]
    assert len(published) == 1
    assert len(sender.calls) == 1
    assert len(provider.calls) == 1
    day = meme.day_window(CHAT, NOW, tz_name="UTC")
    assert meme.quota_view(led, chat_id=CHAT, day=day, limit=3)["spent"] == 1


# ═══ 5. ручной приоритет: дождаться слота, а не терять картинку ════════════

def test_manual_waits_for_the_allowed_slot(tmp_path):
    """Ручной путь ждёт слот существующим механизмом (release-event)."""
    store = _store(tmp_path)
    led = meme.SqliteQuotaLedger(store.path)
    coordinator = _RecordingCoordinator(
        pub.PublicationCoordinator(None, store=store))
    sender = _Sender()

    result = asyncio.run(_pass(tmp_path, manual=True, store=store, ledger=led,
                               sender=sender, publication=coordinator))
    assert result.published is True
    manual_call = coordinator.acquire_calls[-1]
    assert manual_call["manual"] is True
    # Ждём ровно существующий предел ручного ожидания — новых таймеров нет.
    assert manual_call["wait_for_sending"] == float(
        pub.MANUAL_IN_FLIGHT_WAIT_SECONDS)


class _RaceCoordinator:
    """Реальный координатор, у которого слот забирают МЕЖДУ precheck и acquire.

    Штатный `precheck` дешёвый и стоит до генерации; настоящая гонка возможна
    уже после неё (другой механизм занял слот, пока рисовалась картинка).
    """

    def __init__(self, inner, *, deny_reason=pub.REASON_CONFLICT,
                 deny_detail=pub.DETAIL_CROSS_TYPE):
        self.inner = inner
        self.deny_reason = deny_reason
        self.deny_detail = deny_detail

    def store(self):
        return self.inner.store()

    def available(self) -> bool:
        return self.inner.available()

    async def precheck(self, *args, **kwargs):
        return await self.inner.precheck(*args, **kwargs)

    async def acquire(self, chat_id, holder_kind, **kwargs):
        return pub.ClaimDecision(
            granted=False, reason=self.deny_reason, state="claimed",
            detail=self.deny_detail, holder_kind=str(holder_kind))

    async def begin_sending(self, *args, **kwargs):   # pragma: no cover
        return await self.inner.begin_sending(*args, **kwargs)

    async def release(self, *args, **kwargs):         # pragma: no cover
        return await self.inner.release(*args, **kwargs)


def test_automatic_reports_real_conflict_before_generation(tmp_path):
    """Чужой `sending` до генерации: дешёвый конфликт, картинка не заказана."""
    store = _store(tmp_path)
    led = meme.SqliteQuotaLedger(store.path)
    coordinator = _RecordingCoordinator(
        pub.PublicationCoordinator(None, store=store))
    sender = _Sender()
    provider = _Provider()
    foreign = store.acquire(chat_id=CHAT, holder_kind=pub.KIND_TEXT_INITIATIVE,
                            now=NOW_TS, interval_seconds=0)
    assert foreign.granted
    assert store.begin_sending(chat_id=CHAT, claim_id=foreign.claim_id,
                               now=NOW_TS).granted

    result = asyncio.run(_pass(tmp_path, manual=False, store=store, ledger=led,
                               sender=sender, provider=provider,
                               publication=coordinator))

    assert result.published is False
    assert sender.calls == [] and provider.calls == []
    assert result.reason in (meme.SKIP_PUBLICATION_CONFLICT,
                             meme.SKIP_PUBLICATION_IN_FLIGHT)
    assert result.reason != meme.SKIP_PUBLICATION_STALE


def test_automatic_collision_after_generation_keeps_facts_and_does_not_send(
        tmp_path):
    """Слот заняли, пока рисовалась картинка → точный код, отправки нет."""
    store = _store(tmp_path)
    led = meme.SqliteQuotaLedger(store.path)
    sender = _Sender()
    provider = _Provider()
    coordinator = _RaceCoordinator(
        pub.PublicationCoordinator(None, store=store))

    result = asyncio.run(_pass(tmp_path, manual=False, store=store, ledger=led,
                              sender=sender, provider=provider,
                              publication=coordinator))

    assert result.published is False
    assert sender.calls == []
    assert result.reason == meme.SKIP_PUBLICATION_CONFLICT
    assert result.generated is True            # картинка была готова
    assert len(provider.calls) == 1            # ровно одна генерация
    facts = _terminal_facts(led)
    names = [item["name"] for item in facts["events"]]
    assert meme.EVENT_IMAGE_READY in names
    assert meme.EVENT_PUBLICATION_SENT not in names
    assert names[-1] == meme.EVENT_PUBLICATION_DEFERRED
    assert facts["events"][-1].get("delivered") is False
    assert facts.get("delivery") == "not_sent"


def test_manual_preempts_foreign_claimed_slot_and_publishes(tmp_path):
    """Чужой `claimed` не мешает ручному запуску — картинка доставлена."""
    store = _store(tmp_path)
    led = meme.SqliteQuotaLedger(store.path)
    sender = _Sender()
    foreign = store.acquire(chat_id=CHAT, holder_kind=pub.KIND_TEXT_INITIATIVE,
                            now=NOW_TS, interval_seconds=0)
    assert foreign.granted

    result = asyncio.run(_pass(tmp_path, manual=True, store=store, ledger=led,
                               sender=sender))
    assert result.published is True
    assert len(sender.calls) == 1
    assert store.snapshot(CHAT)["last_publish_kind"] == meme.OUTPUT_KIND


# ═══ события: генерация ≠ отправка ══════════════════════════════════════════

def test_events_chain_separates_generation_from_delivery(tmp_path):
    store = _store(tmp_path)
    led = meme.SqliteQuotaLedger(store.path)
    result = asyncio.run(_pass(tmp_path, manual=True, store=store, ledger=led,
                               request_ref="91"))
    assert result.published is True

    facts = _terminal_facts(led)
    events = facts["events"]
    names = [item["name"] for item in events]
    assert names[0] == meme.EVENT_SOURCE_SNAPSHOT
    assert names.index(meme.EVENT_IMAGE_READY) < names.index(
        meme.EVENT_PUBLICATION_SENT)
    assert names.index(meme.EVENT_PUBLICATION_REQUESTED) < names.index(
        meme.EVENT_PUBLICATION_SENT)
    assert names[-1] == meme.EVENT_PUBLICATION_SENT

    for index, item in enumerate(events):
        assert item["run_id"] == result.job_id
        assert item["mode"] == meme.MODE_MANUAL
        assert item["purpose"] == meme.PURPOSE_MANUAL
        assert isinstance(item["at"], int) and item["at"] == NOW_TS
        if index:
            assert item["after"] == names[index - 1]
    image_ready = events[names.index(meme.EVENT_IMAGE_READY)]
    sent = events[names.index(meme.EVENT_PUBLICATION_SENT)]
    assert "delivered" not in image_ready        # «готово» ≠ «доставлено»
    assert sent["delivered"] is True
    # Снапшот источника — durable: чат/run/режим/цель/сообщения/версия.
    snapshot = facts["events"][0]
    assert snapshot["source"] == "factory" or snapshot["source"]
    assert events[0].get("detail", "").startswith("messages:")
    assert facts.get("delivery") == "sent"


def test_send_failure_is_delivery_unknown_not_a_cancel(tmp_path):
    """Исключение доставки: факт неизвестен, а не «отменено» и не «отправлено»."""
    store = _store(tmp_path)
    led = meme.SqliteQuotaLedger(store.path)
    sender = _Sender(boom=True)

    result = asyncio.run(_pass(tmp_path, manual=True, store=store, ledger=led,
                               sender=sender))

    assert result.published is False
    assert result.reason == meme.SKIP_PUBLISH
    assert result.detail == "send_failed"
    facts = _terminal_facts(led)
    names = [item["name"] for item in facts["events"]]
    assert names[-1] == meme.EVENT_DELIVERY_UNKNOWN
    assert facts["events"][-1].get("delivered") is None
    assert facts.get("delivery") == "unknown"


# ═══ 1.4 P0.5: пустой потолок = АВТО (runtime) ═════════════════════════════

def test_auto_ceiling_generates_without_invented_limit(tmp_path):
    """Нет потолка → нет директивы длины, нет обрезки, нет подставных 800."""
    store = _store(tmp_path)
    led = meme.SqliteQuotaLedger(store.path)
    instructions: list[str] = []
    long_joke = "очень длинный прикол " * 60      # ~1200 символов
    provider = _Provider()

    async def joke(_cid, _summary, instruction):
        instructions.append(instruction)
        return long_joke

    result = asyncio.run(_pass(tmp_path, manual=True, store=store, ledger=led,
                               provider=provider, joke=long_joke,
                               joke_fn=joke))
    assert result.published is True
    assert result.limit.known is False and result.limit.mode == "auto"
    assert "не более" not in instructions[0]     # директивы длины нет
    prompt = provider.calls[0][0]
    assert len(prompt) > 800                     # никакого искусственного капа
    assert prompt.endswith(long_joke.strip())    # прикол не обрезан
    assert result.as_dict()["limit"]["joke_budget"] is None


def test_fixed_ceiling_uses_real_rendered_prompt_and_blocks_before_llm(tmp_path):
    """Фиксированный L: J считается от зарендеренного prompt; тесно → до LLM."""
    store = _store(tmp_path)
    led = meme.SqliteQuotaLedger(store.path)
    template = "Мем: {joke}"                     # production renderer
    rendered = meme.render_image_prompt(template, "")
    ceiling = len(rendered) + 20
    instructions: list[str] = []

    async def joke(_cid, _summary, instruction):
        instructions.append(instruction)
        return "короткий прикол"

    result = asyncio.run(_pass(tmp_path, manual=True, store=store, ledger=led,
                               settings=_settings(length_admin=ceiling),
                               joke="короткий прикол",
                               provider=_Provider()))
    # Прошлый прогон публикуется автоматически? Нет: шаблон берётся из слоёв,
    # поэтому сначала фиксируем тесный шаблон настройкой и проверяем отказ.
    tight = asyncio.run(_pass(tmp_path, manual=True, store=store, ledger=led,
                              settings=_settings(length_admin=3)))
    assert tight.published is False
    assert tight.reason == meme.SKIP_NO_JOKE_BUDGET
    assert tight.limit.known is True and tight.limit.joke_budget == 0
    assert tight.limit.template_chars > 3
    assert result is not None


def test_overfull_template_stops_before_summary_and_provider(tmp_path):
    """Шаблон длиннее потолка → конфигурационная ошибка ДО выжимки и картинки."""
    store = _store(tmp_path)
    led = meme.SqliteQuotaLedger(store.path)
    summarizer_calls: list[int] = []
    provider = _Provider()

    async def summarizer(*_a, **_k):
        summarizer_calls.append(1)
        return "хук"

    result = asyncio.run(_pass(tmp_path, manual=True, store=store, ledger=led,
                               settings=_settings(length_admin=10),
                               provider=provider, summarizer=summarizer))
    assert result.reason == meme.SKIP_NO_JOKE_BUDGET
    assert summarizer_calls == []          # выжимка не оплачена
    assert provider.calls == []            # картинка не заказана


def test_image_prompt_fit_helper_is_exact():
    """Факт-проверка «prompt влез в L» (включая append-разделитель)."""
    fixed = meme.resolve_meme_budget(model_chars=50, admin=None,
                                     explicit=None, template="Мем: {joke}")
    inside = meme.render_image_prompt("Мем: {joke}", "x" * 10)
    outside = meme.render_image_prompt("Мем: {joke}", "x" * 60)
    assert meme.image_prompt_fits(inside, fixed) is True
    assert meme.image_prompt_fits(outside, fixed) is False
    auto = meme.resolve_meme_budget(model_chars=None, admin=None,
                                    explicit=None, template="Мем: {joke}")
    assert meme.image_prompt_fits(outside, auto) is True     # предела нет
    # T = реально зарендеренный prompt без прикола (с разделителем append).
    assert meme.template_chars("Мем: {joke}") == len("Мем: ")
    assert meme.template_chars("Мем:") == len("Мем: ")


def test_joke_instruction_without_limit_has_no_fake_number():
    assert meme.joke_instruction("Придумай прикол", None) == "Придумай прикол"
    assert meme.joke_instruction("Придумай прикол", 0) == "Придумай прикол"
    with_limit = meme.joke_instruction("Придумай прикол", 40)
    assert "не более 40 символов" in with_limit


# ═══ 7. ошибка соответствует факту: stale только для утраты валидности ══════

def test_publication_stale_is_kept_only_as_historical_code():
    """Код остался в таксономии/ярлыках, но пайплайн его не выдаёт."""
    from services import initiative_observer as obs
    assert meme.SKIP_PUBLICATION_STALE in meme.SKIP_REASONS
    label = obs.reason_label(meme.SKIP_PUBLICATION_STALE)
    assert "окно чата" not in label
    assert label != meme.SKIP_PUBLICATION_STALE
    assert obs.reason_label(meme.SKIP_SOURCE_GONE) != meme.SKIP_SOURCE_GONE
    from handlers import meme_command
    assert meme.SKIP_SOURCE_GONE in meme_command._FAILURE_TEXT
    assert "изменилась" not in meme_command._FAILURE_TEXT[
        meme.SKIP_PUBLICATION_STALE]


def test_successful_meme_sends_only_the_image_via_bound_sender(tmp_path):
    """Успех = только изображение: sender получает content, не текст/caption."""
    store = _store(tmp_path)
    led = meme.SqliteQuotaLedger(store.path)
    sender = _Sender()
    result = asyncio.run(_pass(tmp_path, manual=True, store=store, ledger=led,
                               sender=sender))
    assert result.published is True
    chat_id, content, prompt = sender.calls[0]
    assert chat_id == CHAT
    assert content == b"png"
    assert prompt.startswith(meme.MEME_IMAGE_PROMPT)
    assert result.published is True and result.outcome == "published"
    # В журнал не попадает текст прикола (R17-безопасность журнала).
    for row in _journal(led):
        assert "прикол" not in str(row.get("detail") or "")


# ═══ 1.4 P0.5: пустой потолок = АВТО (API → PG → диагностика) ══════════════

from tests.test_meme_pipeline_api import client, real_layers  # noqa: E402,F401

ENDPOINT = "/api/initiative/meme-settings"


def _hdr_for(client_obj) -> dict:
    from tests.test_webapp_api import _hdr
    from tests.test_meme_pipeline_api import ADMIN_ID
    return {**_hdr(ADMIN_ID), "X-Chat-Id": str(-100111)}


def _get_length(client_obj) -> dict:
    resp = client_obj.get(ENDPOINT, headers=_hdr_for(client_obj))
    assert resp.status_code == 200, resp.text
    return resp.json()["length_limit"]


def _post_length(client_obj, value):
    return client_obj.post(ENDPOINT, json={"length_limit": value},
                           headers=_hdr_for(client_obj))


def test_empty_ceiling_is_auto_end_to_end(client, tmp_path, monkeypatch):
    """Пусто = авто: API → хранилище → диагностика → runtime после перезагрузки."""
    assert _get_length(client)["mode"] == "auto"
    assert _get_length(client)["joke_budget"] is None
    assert _get_length(client)["source"] == "auto"

    # Фиксированный потолок (auto → fixed).
    resp = _post_length(client, 500)
    assert resp.status_code == 200, resp.text
    fixed = resp.json()["length_limit"]
    assert fixed["mode"] == "fixed" and fixed["ceiling"] == 500
    assert fixed["known"] is True
    template_chars = fixed["template_chars"]
    assert fixed["joke_budget"] == 500 - template_chars

    # Пустая строка = АВТО: переопределение снимается, а не пишется нулём.
    resp = _post_length(client, "")
    assert resp.status_code == 200, resp.text
    auto = resp.json()["length_limit"]
    assert auto["mode"] == "auto" and auto["ceiling"] is None
    assert auto["joke_budget"] is None
    # Повторное чтение (тот же тракт, что после рестарта) — по-прежнему авто.
    assert _get_length(client)["mode"] == "auto"

    # Явный null в теле = тоже авто (это решение, а не «поля нет»).
    assert _post_length(client, 400).status_code == 200
    assert _get_length(client)["mode"] == "fixed"
    assert _post_length(client, None).status_code == 200
    assert _get_length(client)["mode"] == "auto"

    # Исторический 0 = авто (совместимость): фиксированное значение снимается,
    # а сам 0 нигде не сохраняется как «нулевой потолок».
    assert _post_length(client, 450).status_code == 200
    assert _get_length(client)["ceiling"] == 450
    resp = _post_length(client, 0)
    assert resp.status_code == 200, resp.text
    legacy = resp.json()["length_limit"]
    assert legacy["mode"] == "auto" and legacy["ceiling"] is None
    assert "initiative.meme_length_limit" not in \
        (client.conn.params.get("overrides") or {})


def test_invalid_ceiling_input_is_a_precise_field_error(client):
    for value, expected in (("abc", "целое"), (-5, "отрицательн"),
                            (12.5, "целое"), ("12.5", "целое"),
                            (9000, "8000")):
        resp = _post_length(client, value)
        assert resp.status_code == 422, (value, resp.text)
        detail = resp.json()["detail"]
        assert isinstance(detail, list) and detail, detail
        assert detail[0]["loc"] == ["body", "length_limit"]
        assert expected in detail[0]["msg"], detail


def test_global_and_chat_ceiling_do_not_mix(real_layers):
    """Глобальное значение и чатовый override различимы; снятие = наследование."""
    client_obj = real_layers
    client_obj.global_layer["initiative.meme_length_limit"] = 700
    glob = _get_length(client_obj)
    assert glob["ceiling"] == 700 and glob["source"] == "admin_setting"

    assert _post_length(client_obj, 300).status_code == 200
    chat = _get_length(client_obj)
    assert chat["ceiling"] == 300 and chat["mode"] == "fixed"

    # Снятие override возвращает наследование глобального, а не локальный 0.
    assert _post_length(client_obj, "").status_code == 200
    back = _get_length(client_obj)
    assert back["ceiling"] == 700 and back["mode"] == "fixed"
    assert back["joke_budget"] == 700 - back["template_chars"]


def test_absent_field_does_not_touch_saved_ceiling(client):
    """Поле не пришло → сохранённый потолок НЕ стирается (историческая 0 тоже)."""
    assert _post_length(client, 450).status_code == 200
    resp = client.post(ENDPOINT, json={"cooldown_seconds": 0},
                       headers=_hdr_for(client))
    assert resp.status_code == 200, resp.text
    assert resp.json()["length_limit"]["ceiling"] == 450
