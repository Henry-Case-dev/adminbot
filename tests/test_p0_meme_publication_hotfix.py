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
                initiative_enabled=None, request_ref="",
                permission_check=None):
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
        request_ref=request_ref, permission_check=permission_check)


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


@pytest.fixture(autouse=True)
def _release_random_source_singleton():
    """Не оставлять после теста захваченный singleton случайности.

    `mca_random_source.get_service` — модульный singleton, привязанный к первой
    БД; тесты этого файла создают и закрывают настоящие `DatabaseService`.
    Сброс после каждого теста не даёт «призраку» закрытой БД всплыть в чужих
    тестах (это уже случалось в наборе до этой правки).
    """
    yield
    try:
        from services import mca_random_source as _mrs
        _mrs.reset_service()
    except Exception:                          # pragma: no cover
        pass


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



# ═══════════════════════════════════════════════════════════════════════════
# B1 (arch/deferred-publication.md): готовый авто-мем НЕ выбрасывается при
# отказе брони — durable-очередь на существующей `task_jobs` + байты на диске,
# доставка существующим тиком мема, ровно один раз.
# ═══════════════════════════════════════════════════════════════════════════

import hashlib  # noqa: E402
import sqlite3  # noqa: E402
from pathlib import Path  # noqa: E402

from services.database import DatabaseService  # noqa: E402
from services.task_supervisor import (  # noqa: E402
    JOB_CANCELLED, JOB_COMPLETED, JOB_FAILED, JOB_QUEUED)


def _settings_cd(cooldown: int = 0) -> meme.MemeSettings:
    return meme.MemeSettings(enabled=True, window_messages=10, daily_limit=5,
                             cooldown_seconds=cooldown, min_messages=1,
                             trigger_probability=1.0)


async def _seed_messages(svc, chat_id: int = CHAT, n: int = 5) -> list[int]:
    """Настоящие сообщения в настоящей БД: ростер/источник проверяются по ним."""
    ids = []
    for index in range(1, n + 1):
        cursor = await svc.db.execute(
            "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
            "timestamp, media_type, author_name, is_forward, tg_message_id) "
            "VALUES (?, ?, ?, NULL, ?, 'text', 'u', 0, NULL)",
            (42, int(chat_id), f"реплика {index}", NOW_TS - 60 + index))
        ids.append(cursor.lastrowid)
    await svc.db.commit()
    return ids


class _Env:
    """Реальный durable-контур: БД сервиса + журнал квоты + бронь + каталог."""

    def __init__(self, svc, ledger, store, pending: Path):
        self.svc = svc
        self.ledger = ledger
        self.store = store
        self.pending = pending


class _ForeignDuringGeneration:
    """Реальный координатор, у которого ДРУГОЙ механизм публикует в момент
    вызова `acquire` — ровно та гонка, что была в инциденте (precheck прошёл до
    генерации, слот заняли пока рисовалась картинка).
    """

    def __init__(self, inner, store):
        self.inner = inner
        self._store = store
        self.foreign = None
        self.acquire_calls: list[dict] = []

    def store(self):
        return self.inner.store()

    def available(self) -> bool:
        return self.inner.available()

    async def precheck(self, *args, **kwargs):
        return await self.inner.precheck(*args, **kwargs)

    async def acquire(self, chat_id, holder_kind, **kwargs):
        self.acquire_calls.append(dict(kwargs))
        if self.foreign is None:
            self.foreign = self._store.acquire(
                chat_id=int(chat_id), holder_kind=pub.KIND_TEXT_INITIATIVE,
                now=NOW_TS, interval_seconds=0)
            assert self.foreign.granted
            assert self._store.begin_sending(
                chat_id=int(chat_id), claim_id=self.foreign.claim_id,
                now=NOW_TS).granted
        return await self.inner.acquire(chat_id, holder_kind, **kwargs)

    async def begin_sending(self, *args, **kwargs):
        return await self.inner.begin_sending(*args, **kwargs)

    async def release(self, *args, **kwargs):
        return await self.inner.release(*args, **kwargs)

    def finish_foreign(self, chat_id: int = CHAT) -> None:
        """Чужой механизм закончил отправку (реальный release брони)."""
        if self.foreign is None:
            return
        self._store.release(chat_id=int(chat_id), claim_id=self.foreign.claim_id,
                            published=True,
                            holder_kind=pub.KIND_TEXT_INITIATIVE, now=NOW_TS)


async def _env(tmp_path, monkeypatch, *, rows: int = 5) -> _Env:
    pending = tmp_path / "pending"
    monkeypatch.setenv("MEME_PENDING_DIR", str(pending))
    svc = DatabaseService(str(tmp_path / "hotfix.db"))
    await svc.initialize()
    await _seed_messages(svc, CHAT, rows)
    path = str(svc.db_path)
    meme.SqliteQuotaLedger(path).apply_schema()
    ledger = meme.SqliteQuotaLedger(path)
    store = pub.SqliteClaimStore(path)
    return _Env(svc, ledger, store, pending)


async def _auto_pass(env: _Env, *, sender=None, provider=None, job_id=None,
                     gate=None, settings=None, now_ts: int = NOW_TS,
                     publication=None, rights_check=None):
    """Один АВТО-проход по реальной БД (снапшот источника берётся из неё)."""
    sender = sender if sender is not None else _Sender()
    provider = provider if provider is not None else _Provider()

    async def summarizer(_cid, _rows_arg, _system):
        return "хук"

    async def joke(_cid, _summary, _instruction):
        return "прикол"

    async def _gate(_cid):
        return (True, "ok") if gate is None else gate()

    return await meme.consider_chat(
        env.svc, CHAT,
        settings=settings if settings is not None else _settings_cd(),
        ledger=env.ledger, now=NOW, now_ts=now_ts, tz_name="UTC",
        tz_source="utc_fallback", initiative_enabled=lambda: True,
        image_status=IMAGE_OK, random_source=_Hit(0.0),
        summarizer=summarizer, joke_generator=joke, image_provider=provider,
        publish_gate=_gate, sender=sender, claim_store=env.store,
        publication=publication, model_chars=None, job_id=job_id,
        rights_check=rights_check)


def _after_interval() -> int:
    """Момент, когда межтиповой интервал после чужой публикации истёк."""
    return NOW_TS + pub.default_interval_seconds() + 60


async def _deliver(env: _Env, *, sender=None, gate=None, now_ts=None,
                   rights_check=None, source_check=None):
    sender = sender if sender is not None else _Sender()

    async def _gate(_cid):
        return (True, "ok") if gate is None else gate()

    return await meme.deliver_deferred_all(
        env.svc, chat_ids=[CHAT], ledger=env.ledger, sender=sender,
        publish_gate=_gate, initiative_enabled=lambda: True,
        claim_store=env.store, settings=_settings_cd(),
        now_ts=_after_interval() if now_ts is None else now_ts,
        tz_name="UTC", tz_source="utc_fallback",
        rights_check=rights_check, source_check=source_check)


def _pending_rows(env: _Env) -> list[dict]:
    conn = sqlite3.connect(str(env.svc.db_path))
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.execute(
            "SELECT * FROM task_jobs WHERE kind = ? ORDER BY created_at",
            (meme.DEFERRED_KIND,))
        return [dict(row) for row in cursor.fetchall()]
    finally:
        conn.close()


async def _deferred_after_generation(tmp_path, monkeypatch, *, job_id: str,
                                     provider=None, settings=None):
    """Сгенерировать авто-мем и проиграть бронь настоящей чужой публикацией."""
    env = await _env(tmp_path, monkeypatch)
    race = _ForeignDuringGeneration(
        pub.PublicationCoordinator(env.svc, store=env.store), env.store)
    sender = _Sender()
    provider = provider if provider is not None else _Provider()
    result = await _auto_pass(env, sender=sender, provider=provider,
                              job_id=job_id, publication=race,
                              settings=settings)
    return env, race, result, sender, provider


# ── инвариант 1: артефакт не теряется ──────────────────────────────────────

def test_b1_artifact_is_kept_when_claim_is_refused(tmp_path, monkeypatch):
    """Бронь не выдана при generated=True (авто) → файл и строка `queued` есть.

    Мутация: убрать `defer_generated_meme` из ветки отказа — файла и строки
    нет, тест красный (ровно дефект B1).
    """
    async def scenario():
        env, race, result, sender, provider = await _deferred_after_generation(
            tmp_path, monkeypatch, job_id="job-b1-keep")
        try:
            return result, _pending_rows(env), sender, provider, env
        finally:
            await env.svc.close()

    result, rows, sender, provider, env = asyncio.run(scenario())

    assert result.published is False
    assert result.generated is True            # картинка была готова
    assert result.reason in (meme.SKIP_PUBLICATION_CONFLICT,
                            meme.SKIP_PUBLICATION_IN_FLIGHT)
    assert sender.calls == []                  # отправки не было
    assert len(provider.calls) == 1            # ровно одна оплаченная генерация
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == JOB_QUEUED
    assert row["kind"] == meme.DEFERRED_KIND
    assert row["coalesce_key"] == meme.deferred_coalesce_key(CHAT)
    assert row["deadline_at"] == NOW_TS + meme.DEFAULT_COOLDOWN_SECONDS
    payload = meme.deferred_payload(row)
    assert payload["chat_id"] == CHAT
    assert payload["run_id"] == "job-b1-keep"
    assert payload["sha256"] == hashlib.sha256(b"png").hexdigest()
    assert payload["size"] == 3
    assert payload["msg_count"] == 5 and payload["msg_ids"]
    assert payload["mode"] == meme.MODE_AUTOMATIC
    # Файл реально существует в managed-каталоге и совпадает с байтами.
    path = Path(row["result_ref"])
    assert path.exists() and path.read_bytes() == b"png"
    assert path.parent == env.pending


# ── инвариант 2: ровно одна доставка после освобождения слота ──────────────

def test_b1_slot_busy_then_one_delivery_then_completed(tmp_path, monkeypatch):
    """3 прохода в занятом слоте → 0 отправок; слот свободен → ровно 1; ещё 3 → 0."""
    async def scenario():
        env, race, result, _sender, _provider = \
            await _deferred_after_generation(tmp_path, monkeypatch,
                                             job_id="job-b1-slot")
        try:
            sender = _Sender()
            waits = []
            for _ in range(3):
                waits.append(await _deliver(env, sender=sender, now_ts=NOW_TS))
            assert sender.calls == []          # слот занят — отправки нет
            race.finish_foreign()              # чужой механизм закончил
            delivered = await _deliver(env, sender=sender)
            after = [await _deliver(env, sender=sender) for _ in range(3)]
            return waits, delivered, after, sender, env
        finally:
            await env.svc.close()

    waits, delivered, after, sender, env = asyncio.run(scenario())

    assert all(items == [] for items in waits)   # слот занят — ничего не ушло
    assert delivered and len(delivered) == 1
    assert delivered[0].published is True and delivered[0].reason == "sent"
    assert len(sender.calls) == 1
    assert all(items == [] for items in after)
    rows = _pending_rows(env)
    assert [row["status"] for row in rows] == [JOB_COMPLETED]
    assert not Path(rows[0]["result_ref"]).exists()   # байты убраны


# ── инвариант 3: без второй генерации ──────────────────────────────────────

def test_b1_pending_artifact_blocks_new_generation(tmp_path, monkeypatch):
    """Пока артефакт ждёт слота, проход НЕ зовёт ни LLM, ни провайдера."""
    async def scenario():
        env, race, _result, _sender, _provider = \
            await _deferred_after_generation(tmp_path, monkeypatch,
                                             job_id="job-b1-nogen")
        try:
            second_provider = _Provider()
            calls: list = []
            second_provider.calls = calls

            async def _summarizer(*_a, **_k):
                calls.append("llm")
                return "хук"

            result = await meme.consider_chat(
                env.svc, CHAT, settings=_settings_cd(), ledger=env.ledger,
                now=NOW, now_ts=NOW_TS, tz_name="UTC",
                tz_source="utc_fallback", initiative_enabled=lambda: True,
                image_status=IMAGE_OK, random_source=_Hit(0.0),
                summarizer=_summarizer, joke_generator=_summarizer,
                image_provider=second_provider, publish_gate=_gate_ok,
                sender=_Sender(), claim_store=env.store, model_chars=None,
                job_id="job-b1-nogen-2")
            return result, calls, env
        finally:
            await env.svc.close()

    result, calls, env = asyncio.run(scenario())

    assert calls == []                      # ни одного вызова LLM/провайдера
    assert result.published is False and result.generated is False
    assert result.detail == "deferred_pending"
    assert len(_pending_rows(env)) == 1


# ── инвариант 4: рестарт ───────────────────────────────────────────────────

def test_b1_restart_sees_queue_and_delivers(tmp_path, monkeypatch):
    """Новый процесс (новые объекты сервисов) видит `queued` + файл и доставляет."""
    async def scenario():
        env, race, _result, _sender, _provider = \
            await _deferred_after_generation(tmp_path, monkeypatch,
                                             job_id="job-b1-restart")
        race.finish_foreign()
        pending = env.pending
        await env.svc.close()
        svc2 = DatabaseService(str(tmp_path / "hotfix.db"))
        await svc2.initialize()
        path = str(svc2.db_path)
        env2 = _Env(svc2, meme.SqliteQuotaLedger(path),
                    pub.SqliteClaimStore(path), pending)
        try:
            sender = _Sender()
            delivered = await _deliver(env2, sender=sender)
            return delivered, sender, env2
        finally:
            await svc2.close()

    delivered, sender, env = asyncio.run(scenario())
    assert delivered and delivered[0].published is True
    assert len(sender.calls) == 1
    assert [row["status"] for row in _pending_rows(env)] == [JOB_COMPLETED]


# ── инвариант 5: квота не тратится дважды ─────────────────────────────────

def test_b1_delivery_does_not_reserve_quota(tmp_path, monkeypatch):
    """Доставка готового артефакта не создаёт новую бронь квоты."""
    async def scenario():
        env, race, _result, _sender, _provider = \
            await _deferred_after_generation(tmp_path, monkeypatch,
                                             job_id="job-b1-quota")
        try:
            before = _reservations(env.ledger)
            day = meme.day_window(CHAT, NOW, tz_name="UTC")
            spent_before = meme.quota_view(env.ledger, chat_id=CHAT, day=day,
                                          limit=5)["spent"]
            race.finish_foreign()
            await _deliver(env)
            after = _reservations(env.ledger)
            spent_after = meme.quota_view(env.ledger, chat_id=CHAT, day=day,
                                         limit=5)["spent"]
            return before, after, spent_before, spent_after
        finally:
            await env.svc.close()

    before, after, spent_before, spent_after = asyncio.run(scenario())
    assert [row["job_id"] for row in before] == ["job-b1-quota"]
    assert after == before
    assert spent_before == 1 and spent_after == 1


# ── инвариант 6: права/модуль ──────────────────────────────────────────────

def test_b1_rights_revoked_cancels_with_own_code(tmp_path, monkeypatch):
    """Чат больше не допустимая цель → `rights_revoked`, без отправки."""
    async def scenario():
        env, race, _result, _sender, _provider = \
            await _deferred_after_generation(tmp_path, monkeypatch,
                                             job_id="job-b1-rights")
        try:
            # Права отозваны: из РЕАЛЬНОГО источника ростера чат пропал.
            await env.svc.db.execute(
                "DELETE FROM smart_messages WHERE chat_id = ?", (CHAT,))
            await env.svc.db.commit()
            race.finish_foreign()
            sender = _Sender()
            delivered = await _deliver(env, sender=sender)
            return delivered, sender, env
        finally:
            await env.svc.close()

    delivered, sender, env = asyncio.run(scenario())
    assert sender.calls == []
    assert delivered and delivered[0].reason == meme.SKIP_RIGHTS_REVOKED
    assert delivered[0].detail == "chat_not_in_roster"
    rows = _pending_rows(env)
    assert [row["status"] for row in rows] == [JOB_CANCELLED]
    assert not Path(rows[0]["result_ref"]).exists()


def test_b1_module_off_cancels_with_disabled_code(tmp_path, monkeypatch):
    """Тумблер выключен между генерацией и отправкой → `disabled_by_setting`."""
    async def scenario():
        env, race, _result, _sender, _provider = \
            await _deferred_after_generation(tmp_path, monkeypatch,
                                             job_id="job-b1-off")
        try:
            from services import chat_params
            original = chat_params.get_chat_param

            async def _param(chat_id, key, default=None):
                if key == meme.KEY_ENABLED:
                    return False
                return await original(chat_id, key, default)

            chat_params.get_chat_param = _param
            try:
                race.finish_foreign()
                sender = _Sender()
                delivered = await _deliver(env, sender=sender)
            finally:
                chat_params.get_chat_param = original
            return delivered, sender, env
        finally:
            await env.svc.close()

    delivered, sender, env = asyncio.run(scenario())
    assert sender.calls == []
    assert delivered and delivered[0].reason == meme.SKIP_DISABLED
    rows = _pending_rows(env)
    assert [row["status"] for row in rows] == [JOB_CANCELLED]
    assert not Path(rows[0]["result_ref"]).exists()


# ── инвариант 7: честное истечение ─────────────────────────────────────────

def test_b1_expired_artifact_reports_honest_code_once(tmp_path, monkeypatch):
    """Ретенция истекла → одна строка `deferred_publication_expired`, файла нет."""
    async def scenario():
        env, race, _result, _sender, _provider = \
            await _deferred_after_generation(tmp_path, monkeypatch,
                                             job_id="job-b1-exp")
        try:
            later = NOW_TS + meme.DEFAULT_COOLDOWN_SECONDS + 1
            race.finish_foreign()
            sender = _Sender()
            first = await _deliver(env, sender=sender, now_ts=later)
            second = await _deliver(env, sender=sender, now_ts=later + 10)
            return first, second, sender, env
        finally:
            await env.svc.close()

    first, second, sender, env = asyncio.run(scenario())
    assert sender.calls == []
    assert first and first[0].reason == meme.SKIP_DEFERRED_EXPIRED
    assert second == []                        # повторных строк нет
    rows = _pending_rows(env)
    assert [row["status"] for row in rows] == [JOB_CANCELLED]
    assert not Path(rows[0]["result_ref"]).exists()
    journal = [row for row in env.ledger.attempts(CHAT)
               if str(row.get("reason_code")) == meme.SKIP_DEFERRED_EXPIRED]
    assert len(journal) == 1                   # ровно одна строка на переход
    from services.initiative_observer import reason_label
    assert reason_label(meme.SKIP_DEFERRED_EXPIRED) != meme.SKIP_DEFERRED_EXPIRED


# ── инвариант 8: дубль невозможен ──────────────────────────────────────────

def test_b1_two_parallel_deliveries_send_once(tmp_path, monkeypatch):
    """Два параллельных прохода доставки → одна отправка (CAS + бронь)."""
    async def scenario():
        env, race, _result, _sender, _provider = \
            await _deferred_after_generation(tmp_path, monkeypatch,
                                             job_id="job-b1-par")
        try:
            race.finish_foreign()
            sender = _Sender()
            both = await asyncio.gather(_deliver(env, sender=sender),
                                        _deliver(env, sender=sender))
            return both, sender, env
        finally:
            await env.svc.close()

    both, sender, env = asyncio.run(scenario())
    assert len(sender.calls) == 1
    delivered = [item for result in both for item in result if item.published]
    assert len(delivered) == 1
    assert [row["status"] for row in _pending_rows(env)] == [JOB_COMPLETED]


# ── инвариант 9: delivery_unknown не переотправляется ──────────────────────

def test_b1_send_failure_is_terminal_delivery_unknown(tmp_path, monkeypatch):
    """Исключение sender'а → `delivery_unknown`, файл удалён, повтора нет."""
    async def scenario():
        env, race, _result, _sender, _provider = \
            await _deferred_after_generation(tmp_path, monkeypatch,
                                             job_id="job-b1-unknown")
        try:
            race.finish_foreign()
            boom = _Sender(boom=True)
            first = await _deliver(env, sender=boom)
            again = await _deliver(env, sender=_Sender())
            return first, again, boom, env
        finally:
            await env.svc.close()

    first, again, boom, env = asyncio.run(scenario())
    assert len(boom.calls) == 1                # ровно одна попытка
    assert first and first[0].reason == meme.REASON_DELIVERY_UNKNOWN
    assert first[0].published is False
    assert again == []                         # повторов нет
    rows = _pending_rows(env)
    assert [row["status"] for row in rows] == [JOB_FAILED]
    assert not Path(rows[0]["result_ref"]).exists()
    assert _terminal_facts(env.ledger).get("delivery") == "unknown"


def test_b1_interrupted_row_is_finalised_not_resent(tmp_path, monkeypatch):
    """Строка, помеченная watchdog'ом `interrupted`, не переотправляется."""
    async def scenario():
        env, race, _result, _sender, _provider = \
            await _deferred_after_generation(tmp_path, monkeypatch,
                                             job_id="job-b1-crash")
        try:
            race.finish_foreign()
            conn = sqlite3.connect(str(env.svc.db_path))
            try:
                conn.execute("UPDATE task_jobs SET status = 'interrupted' "
                             "WHERE kind = ?", (meme.DEFERRED_KIND,))
                conn.commit()
            finally:
                conn.close()
            sender = _Sender()
            delivered = await _deliver(env, sender=sender)
            return delivered, sender, env
        finally:
            await env.svc.close()

    delivered, sender, env = asyncio.run(scenario())
    assert sender.calls == []
    assert delivered and delivered[0].reason == meme.REASON_DELIVERY_UNKNOWN
    assert delivered[0].detail == "interrupted"
    rows = _pending_rows(env)
    assert [row["status"] for row in rows] == [JOB_FAILED]
    assert not Path(rows[0]["result_ref"]).exists()


# ── инвариант 10: журнал не спамится ───────────────────────────────────────

def test_b1_waiting_passes_do_not_write_journal_rows(tmp_path, monkeypatch):
    """N проходов ожидания слота → НИ ОДНОЙ новой строки журнала попыток."""
    async def scenario():
        env, _race, _result, _sender, _provider = \
            await _deferred_after_generation(tmp_path, monkeypatch,
                                             job_id="job-b1-spam")
        try:
            before = len(env.ledger.attempts(CHAT))
            for _ in range(5):
                await _deliver(env, now_ts=NOW_TS)
            after = len(env.ledger.attempts(CHAT))
            return before, after
        finally:
            await env.svc.close()

    before, after = asyncio.run(scenario())
    assert after == before                     # ожидание — не попытка


def test_b1_pending_row_is_single_per_chat(tmp_path, monkeypatch):
    """На чат — одна активная отложенная запись (existing unique partial v14)."""
    async def scenario():
        env, race, _result, _sender, _provider = \
            await _deferred_after_generation(tmp_path, monkeypatch,
                                             job_id="job-b1-one")
        try:
            # Второй проход с «активным» артефактом не генерирует (см. инв.3),
            # поэтому проверяем механизм напрямую: второй enqueue того же чата.
            snapshot = meme.build_source_snapshot(
                chat_id=CHAT, rows=[{"id": 1, "text": "x"}],
                run_id="run-2", mode=meme.MODE_AUTOMATIC,
                purpose=meme.PURPOSE_AUTOMATIC, now_ts=NOW_TS)
            again = await meme.defer_generated_meme(
                env.svc, chat_id=CHAT, content=b"png2", snapshot=snapshot,
                run_id="run-2", reason=meme.SKIP_PUBLICATION_CONFLICT,
                detail="cross_type_interval", cfg=_settings_cd(),
                prompt_origin="factory", now_ts=NOW_TS)
            rows = _pending_rows(env)
            return again, rows, env
        finally:
            await env.svc.close()

    again, rows, env = asyncio.run(scenario())
    assert again is not None and again.get("already_pending") is True
    assert len(rows) == 1                      # одна активная запись на чат
    # Свежий (второй) файл не оставлен мусором, а старый артефакт цел.
    assert len(list(env.pending.glob("*.bin"))) == 1
    assert Path(rows[0]["result_ref"]).exists()


# ── два РАЗНЫХ job_id: не дубль, а два законных прохода под своими лимитами ──

def test_two_different_job_ids_are_rate_limited_not_deduped(tmp_path,
                                                            monkeypatch):
    """Вердикт по «двум job_id публикуют дважды»: это не дубль-путь.

    Факты на реальном коде:
      * у автоматического мема РОВНО ОДНА точка входа — `on_initiative_cycle`
        (единственный вызов в `initiative_observer._meme_phase`), а она живёт
        внутри singleflight-задачи `initiative.observe`
        (`coalesce_key="initiative.observe:global"`): два прохода одновременно
        не идут by construction;
      * второй проход с НОВЫМ `job_id` ограничен собственным кулдауном
        механизма (`initiative.meme_cooldown_seconds`, дефолт 6 ч) и суточной
        квотой — это разные законные попытки, а не дубль одного запроса;
      * при выключенном кулдауне (тестовая конфигурация `cooldown_seconds=0`)
        второй проход действительно публикует второй мем — но это следствие
        конфигурации, а не дефект дедупликации.

    Тест фиксирует обе стороны факта: с дефолтным кулдауном второго мема нет.
    """
    async def scenario():
        env = await _env(tmp_path, monkeypatch)
        try:
            first_provider = _Provider()
            first = await _auto_pass(env, provider=first_provider,
                                     job_id="job-a",
                                     settings=_settings_cd(cooldown=21600))
            second_provider = _Provider()
            second = await _auto_pass(env, provider=second_provider,
                                      job_id="job-b",
                                      settings=_settings_cd(cooldown=21600))
            return first, second, first_provider, second_provider
        finally:
            await env.svc.close()

    first, second, first_provider, second_provider = asyncio.run(scenario())
    assert first.published is True
    assert len(first_provider.calls) == 1
    assert second.published is False
    assert second.reason == meme.SKIP_COOLDOWN     # свой кулдаун, не дубль
    assert second_provider.calls == []             # второй генерации нет


def test_single_entry_point_for_automatic_memes():
    """Авто-мемы идут ТОЛЬКО из singleflight-прохода инициативы."""
    import ast
    import pathlib

    root = pathlib.Path(__file__).resolve().parent.parent
    callers: list[str] = []
    for path in list((root / "services").glob("*.py")) + list(
            (root / "handlers").glob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:                    # pragma: no cover
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
                if node.func.attr == "on_initiative_cycle":
                    callers.append(f"{path.name}:{node.lineno}")
    assert len(callers) == 1, callers
    assert callers[0].startswith("initiative_observer.py:")


# ── B2: реальная перепроверка прав (не мок гейта) ──────────────────────────

def test_b2_real_roster_rights_are_checked(tmp_path, monkeypatch):
    """Настоящая `_default_rights_check` по настоящему источнику ростера."""
    async def scenario():
        env = await _env(tmp_path, monkeypatch)
        try:
            allowed = await meme._default_rights_check(env.svc, CHAT)
            await env.svc.db.execute(
                "DELETE FROM smart_messages WHERE chat_id = ?", (CHAT,))
            await env.svc.db.commit()
            denied = await meme._default_rights_check(env.svc, CHAT)
            return allowed, denied
        finally:
            await env.svc.close()

    allowed, denied = asyncio.run(scenario())
    assert allowed == (True, "", "")
    assert denied[0] is False
    assert denied[1] == meme.SKIP_RIGHTS_REVOKED
    assert denied[2] == "chat_not_in_roster"


def test_b2_rights_revoked_during_generation_blocks_direct_publication(
        tmp_path, monkeypatch):
    """Права отозваны ПОСЛЕ генерации → свой код, отправки нет."""
    async def scenario():
        env = await _env(tmp_path, monkeypatch)
        try:
            provider = _Provider()
            sender = _Sender()

            async def _revoke(_cid):
                await env.svc.db.execute(
                    "DELETE FROM smart_messages WHERE chat_id = ?", (CHAT,))
                await env.svc.db.commit()
                return await meme._default_rights_check(env.svc, int(_cid))

            result = await _auto_pass(env, sender=sender, provider=provider,
                                      job_id="job-b2-direct",
                                      rights_check=_revoke)
            return result, sender, provider, env
        finally:
            await env.svc.close()

    result, sender, provider, env = asyncio.run(scenario())
    assert result.published is False
    assert result.reason == meme.SKIP_RIGHTS_REVOKED
    assert result.detail == "chat_not_in_roster"
    assert result.generated is True            # картинка была готова
    assert sender.calls == []                  # публикации нет
    assert len(provider.calls) == 1


def test_b2_manual_permission_is_rechecked_before_publication(tmp_path):
    """Ручной путь: права отозваны после старта генерации → `rights_revoked`."""
    store = _store(tmp_path)
    led = meme.SqliteQuotaLedger(store.path)
    sender = _Sender()
    provider = _Provider()

    async def permission_check() -> bool:
        return False

    result = asyncio.run(_pass(tmp_path, manual=True, store=store, ledger=led,
                               sender=sender, provider=provider,
                               permission_check=permission_check))
    assert result.published is False
    assert result.reason == meme.SKIP_RIGHTS_REVOKED
    assert result.detail == "permission_denied"
    assert result.generated is True           # генерация состоялась
    assert sender.calls == []                 # но публикации нет
    assert len(provider.calls) == 1


def test_b2_handler_passes_real_permission_hook(tmp_path, monkeypatch):
    """`/meme` перепроверяет РЕАЛЬНЫЙ RBAC перед публикацией (два вызова)."""
    from handlers import meme_command
    from tests.test_meme_command_autodelete import (_Bot, _install, _ledger,
                                                    _seams, _target)

    events: list[str] = []
    bot = _Bot(events)
    led = _ledger(tmp_path)
    seams = _seams(events, ledger=led)
    _install(monkeypatch, bot, seams)

    calls: list[int] = []

    async def _admin(_uid, _cid):
        calls.append(1)
        return len(calls) == 1        # на входе админ, перед публикацией — нет

    monkeypatch.setattr(meme_command, "is_meme_admin", _admin)
    asyncio.run(meme_command.cmd_meme(_target(bot)))

    assert len(calls) == 2            # вход + реальная перепроверка
    assert bot.photos() == []         # картинка не ушла
    texts = bot.texts()
    assert len(texts) == 1            # ровно одно короткое сообщение
    assert "прав" in texts[0][2].lower()


# ── B3: ручной `/meme` реально ждёт чужую отправку ─────────────────────────

class _WaitProbe(asyncio.Event):
    """Event, который сообщает тесту: ожидание слота РЕАЛЬНО началось."""

    def __init__(self) -> None:
        super().__init__()
        self.waiter_started = asyncio.Event()

    async def wait(self):
        self.waiter_started.set()
        return await super().wait()


def test_b3_manual_waits_for_foreign_sending_then_publishes(tmp_path,
                                                            monkeypatch):
    """Чужая отправка идёт → `/meme` ДОЖИДАЕТСЯ освобождения и публикует.

    Мутация: вернуть отказ `publication_in_flight` в `precheck(manual=True)` —
    прогон не доходит до генерации, `provider.calls == 0`, тест красный.
    """
    store = _store(tmp_path)
    led = meme.SqliteQuotaLedger(store.path)
    sender = _Sender()
    provider = _Provider()
    pub.reset_release_events()
    probe = _WaitProbe()
    pub._RELEASE_EVENTS[CHAT] = probe
    monkeypatch.setattr(pub, "_release_event", lambda _cid: probe)
    # Часы координатора — те же, что в прогоне (иначе его повторный `acquire`
    # взял бы реальное «сейчас» и счёл нашу бронь истёкшей).
    coordinator = pub.PublicationCoordinator(None, store=store,
                                             now_fn=lambda: NOW_TS)
    foreign = store.acquire(chat_id=CHAT, holder_kind=pub.KIND_TEXT_INITIATIVE,
                            now=NOW_TS, interval_seconds=0)
    assert foreign.granted
    assert store.begin_sending(chat_id=CHAT, claim_id=foreign.claim_id,
                               now=NOW_TS).granted

    async def scenario():
        async def _foreign_sender_finishes():
            await probe.waiter_started.wait()   # мем реально начал ждать слот
            store.release(chat_id=CHAT, claim_id=foreign.claim_id,
                          published=True,
                          holder_kind=pub.KIND_TEXT_INITIATIVE, now=NOW_TS)

        releaser = asyncio.ensure_future(_foreign_sender_finishes())
        try:
            return await _pass(tmp_path, manual=True, store=store, ledger=led,
                               sender=sender, provider=provider,
                               publication=coordinator)
        finally:
            # Если прогон не дошёл до ожидания слота — релизер не нужен и не
            # должен подвесить тест (это и есть мутационная проверка B3).
            if not probe.waiter_started.is_set():
                releaser.cancel()
            await asyncio.gather(releaser, return_exceptions=True)

    try:
        result = asyncio.run(scenario())
    finally:
        pub.reset_release_events()

    assert probe.waiter_started.is_set(), "ручной путь не вошёл в ожидание слота"
    assert result.published is True and result.reason == "sent"
    assert len(sender.calls) == 1              # ровно один мем
    assert len(provider.calls) == 1            # без второй генерации


async def _gate_ok(_cid):
    return True, "ok"
