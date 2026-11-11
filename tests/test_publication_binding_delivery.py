"""P0IM-S5b — оплаченное изображение не выбрасывается из-за несвязанного
отправителя, и его судьба видна в осях доставки/квоты.

Контракт (`requirements-map.json`, срез S5b; источник — строки 27, 83, 120
`plans/owner_inputs/2026-11-11-p0-init-meme-ux-diag-corrective-excerpt.md`,
диагноз `evidence/r0/diagnosis-2.58.188.md` §6 D6):

  * ``P0IM-S5B-NODISCARD`` — авто-мем, у которого картинка уже оплачена,
    не выбрасывается при ``publish_blocked / publisher_not_bound``: результат
    либо восстанавливается СУЩЕСТВУЮЩИМ durable-механизмом отложенной
    публикации, либо закрывается явным исходом «не доставлено» с этой
    причиной. Новых очередей/таблиц/планировщиков нет;
  * ``P0IM-S5B-DELIVERY-FACT`` — для попытки, закрытой без отправки,
    read-model отдаёт ``last_delivery = not_delivered`` с ТОЧНЫМ кодом причины
    (в том числе ``publisher_not_bound``), а не пустоту и не «опубликовано»;
  * ``P0IM-S5B-QUOTA`` — слот, списанный под попытку без доставки, не
    возвращается (списание = реально оплаченный вызов провайдера), но
    показывается как «израсходовано без отправки» с причиной; счётчики
    попытки/картинки/подтверждённой отправки не смешиваются.

Каждая проверка наблюдает реальный результат: настоящие `DatabaseService`,
журнал квоты SQLite, бронь публикации и файл артефакта; подменены только
внешние границы (LLM, image-провайдер, Telegram-отправка, часы).

Мутации, на которых эти тесты обязаны краснеть (проверено вручную, см. отчёт):
  * M1 — убрать вызов ``defer_generated_meme`` в ветке ``publisher_not_bound``:
    падает `test_auto_meme_keeps_paid_image_when_publisher_not_bound`;
  * M2 — вернуть терминал вместо ожидания в отложенном пути при
    ``sender is None``: падает
    `test_deferred_row_waits_for_publisher_and_is_delivered_after_restart`;
  * M3 — не применять факт закрытия попытки к оси доставки и не считать
    слоты без отправки: падают `test_delivery_axis_...` и `test_quota_...`.

TEST-LIFECYCLE: CONTRACT owner=P0IM-S5B (rows P0IM-S5B-NODISCARD /
P0IM-S5B-DELIVERY-FACT / P0IM-S5B-QUOTA)
"""
from __future__ import annotations

import asyncio
import hashlib
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

from services import initiative_diagnostics as diag
from services import initiative_observer as obs
from services import mca_random_source as mrs
from services import meme_initiative as meme
from services import publication_coordination as pub
from services.database import DatabaseService
from services.task_supervisor import (JOB_CANCELLED, JOB_QUEUED,
                                      JOB_COMPLETED, JOB_FAILED)

NOW = datetime(2026, 11, 12, 12, 0, tzinfo=timezone.utc)
NOW_TS = int(NOW.timestamp())
CHAT = -100
IMAGE_OK = {"available": True, "reason": "ok", "health": "healthy",
            "configured": True, "module_enabled": True}
CONTENT = b"paid-png-bytes"


# ── двойники ВНЕШНИХ границ (LLM, провайдер, Telegram) ──────────────────────

class _Hit:
    async def draw_probability(self, **_kwargs):
        return mrs.DrawResult(value=0.0, deferred=False, fallback_reason=None,
                              source="pseudorandom", selected_source="quantum",
                              draw_id="draw-s5b")


class _Provider:
    def __init__(self, *, content: bytes = CONTENT, ok: bool = True):
        self.content = content
        self.ok = ok
        self.calls: list[tuple] = []

    async def __call__(self, prompt, chat_id, job_id):
        self.calls.append((prompt, chat_id, job_id))
        return SimpleNamespace(ok=self.ok, called=True, reason="",
                               content=self.content)


class _Sender:
    def __init__(self, *, message_id: int = 901):
        self.calls: list[tuple] = []
        self.message_id = message_id

    async def __call__(self, chat_id, content, prompt):
        self.calls.append((chat_id, content, prompt))
        return SimpleNamespace(message_id=self.message_id)


# ── реальный durable-контур ─────────────────────────────────────────────────

def _settings(**overrides) -> meme.MemeSettings:
    base = dict(enabled=True, window_messages=8, daily_limit=3,
                cooldown_seconds=1800, min_messages=1,
                trigger_probability=1.0)
    base.update(overrides)
    return meme.MemeSettings(**base)


async def _open(tmp_path, name: str = "s5b.db", *, messages: int = 5):
    """БД + журнал квоты + бронь на одном файле (как в поставке)."""
    svc = DatabaseService(str(tmp_path / name))
    await svc.initialize()
    for index in range(1, messages + 1):
        await svc.db.execute(
            "INSERT INTO smart_messages (user_id, chat_id, text, reply_to_id, "
            "timestamp, media_type, author_name, is_forward, tg_message_id) "
            "VALUES (?, ?, ?, NULL, ?, 'text', 'u', 0, NULL)",
            (42, int(CHAT), f"реплика {index}", NOW_TS - 60 + index))
    await svc.db.commit()
    path = str(svc.db_path)
    meme.SqliteQuotaLedger(path).apply_schema()
    return svc, meme.SqliteQuotaLedger(path), pub.SqliteClaimStore(path)


async def _auto_pass(svc, ledger, *, sender=None, provider=None,
                     settings=None, now_ts: int = NOW_TS):
    """Один АВТО-проход. ``sender=None`` — ровно боевой случай «отправителя
    в этом процессе нет» (событийный тик без привязанного бота)."""
    provider = provider if provider is not None else _Provider()

    async def summarizer(_cid, _rows, _system):
        return "хук"

    async def joke(_cid, _summary, _instruction):
        return "прикол"

    async def gate(_cid):
        return True, "ok"

    return await meme.consider_chat(
        svc, CHAT, settings=settings if settings is not None else _settings(),
        ledger=ledger, now=NOW, now_ts=now_ts, tz_name="UTC",
        tz_source="utc_fallback", initiative_enabled=lambda: True,
        image_status=IMAGE_OK, random_source=_Hit(), summarizer=summarizer,
        joke_generator=joke, image_provider=provider, publish_gate=gate,
        sender=sender, model_chars=None)


async def _tick(svc, ledger, *, sender=None, settings=None,
                now_ts: int = NOW_TS + 60):
    """Один проход доставки отложенных артефактов (существующий тик мема)."""
    async def gate(_cid):
        return True, "ok"

    return await meme.deliver_deferred_all(
        svc, chat_ids=[CHAT], ledger=ledger, sender=sender,
        publish_gate=gate, initiative_enabled=lambda: True,
        settings=settings if settings is not None else _settings(),
        now_ts=now_ts, tz_name="UTC", tz_source="utc_fallback")


def _deferred_rows(svc) -> list[dict]:
    conn = sqlite3.connect(str(svc.db_path))
    conn.row_factory = sqlite3.Row
    try:
        return [dict(row) for row in conn.execute(
            "SELECT * FROM task_jobs WHERE kind = ? ORDER BY created_at",
            (meme.DEFERRED_KIND,)).fetchall()]
    finally:
        conn.close()


def _attempts(ledger, limit: int = 20) -> list[dict]:
    return ledger.attempts(CHAT, limit=limit)


def _terminal_facts(rows: list[dict]) -> dict:
    """Факты терминальной строки самой свежей попытки (журнал как есть)."""
    newest = max(rows, key=lambda row: int(row.get("ts") or 0))
    return meme.parse_attempt_facts(newest)


def _day():
    return meme.day_window(CHAT, NOW, tz_name="UTC", tz_source="utc_fallback")


# ── гейты витрины (внешние швы, не предмет проверки) ───────────────────────

def _stub_gates(monkeypatch, *, settings=None):
    async def _image(_chat_id, health=None):
        return dict(IMAGE_OK)

    monkeypatch.setattr(meme, "image_dependency", _image)
    monkeypatch.setattr(obs, "observer_enabled", lambda: True)

    async def _chat_on(_chat_id):
        return True

    monkeypatch.setattr(obs, "chat_observer_enabled", _chat_on)
    state = SimpleNamespace(
        capability="initiative", key="initiative.enabled", domain="override",
        chat_id=CHAT, chat_state="inherit", desired=True, source="global",
        global_value=True, global_source="hot", emergency_block=False,
        effective_runtime=True, ready=None, reason_code=None)

    async def _state(_chat_id, *, fresh=False):
        return state

    monkeypatch.setattr(obs, "chat_capability_state", _state)
    cfg = settings if settings is not None else _settings()

    async def _load(_chat_id=None):
        return cfg

    monkeypatch.setattr(meme, "load_settings", _load)
    return cfg


# ═══ 1. оплаченное изображение не выбрасывается ══════════════════════════════

def test_auto_meme_keeps_paid_image_when_publisher_not_bound(
        tmp_path, monkeypatch):
    """`sender is None` → байты в существующей durable-очереди, а не в корзине.

    Мутация M1 (убрать `defer_generated_meme` из ветки): строки очереди и
    файла нет — тест красный ровно по дефекту D6.
    """
    pending = tmp_path / "pending"
    monkeypatch.setenv("MEME_PENDING_DIR", str(pending))

    async def scenario():
        svc, ledger, _store = await _open(tmp_path, "nodiscard.db")
        try:
            provider = _Provider()
            result = await _auto_pass(svc, ledger, sender=None,
                                      provider=provider)
            return result, provider, _deferred_rows(svc), _attempts(ledger)
        finally:
            await svc.close()

    result, provider, rows, attempts = asyncio.run(scenario())

    assert result.published is False
    assert result.generated is True                     # картинка оплачена
    assert (result.reason, result.detail) == (
        meme.SKIP_PUBLISH, "publisher_not_bound")
    assert len(provider.calls) == 1                     # ровно один платный вызов
    # Байты существуют в managed-каталоге и совпадают с оплаченным результатом.
    assert len(rows) == 1
    row = rows[0]
    assert row["status"] == JOB_QUEUED
    assert row["coalesce_key"] == meme.deferred_coalesce_key(CHAT)
    payload = meme.deferred_payload(row)
    assert payload["run_id"] == result.job_id
    assert payload["deferred_reason"] == meme.SKIP_PUBLISH
    assert payload["deferred_detail"] == "publisher_not_bound"
    path = Path(row["result_ref"])
    assert path.exists() and path.read_bytes() == CONTENT
    assert path.parent == pending
    assert payload["sha256"] == hashlib.sha256(CONTENT).hexdigest()
    # Журнал попытки говорит то же самое явно, а не «всё хорошо».
    facts = _terminal_facts(attempts)
    assert facts["publication"]["artifact"]["preserved"] is True
    assert facts["publication"]["artifact"]["reason"] == "publisher_not_bound"
    assert facts["publication"]["delivery"] == "not_sent"


def test_without_durable_path_the_attempt_is_closed_with_explicit_reason(
        tmp_path, monkeypatch):
    """Нет durable-пути → честная запись «байты не сохранены», не тишина.

    Это вторая допустимая ветка контракта: явный исход «не доставлено» с
    причиной. `preserved=false` пишется в журнал, а не выдаётся за успех.
    """
    monkeypatch.setenv("MEME_PENDING_DIR", str(tmp_path / "pending"))
    monkeypatch.setattr(meme, "_task_store", lambda _db: None)

    async def scenario():
        svc, ledger, _store = await _open(tmp_path, "nodurable.db")
        try:
            result = await _auto_pass(svc, ledger, sender=None)
            return result, _deferred_rows(svc), _attempts(ledger)
        finally:
            await svc.close()

    result, rows, attempts = asyncio.run(scenario())

    assert result.published is False and result.generated is True
    assert (result.reason, result.detail) == (
        meme.SKIP_PUBLISH, "publisher_not_bound")
    assert rows == []                                   # откладывать некуда
    facts = _terminal_facts(attempts)
    assert facts["publication"]["artifact"]["preserved"] is False
    assert facts["publication"]["delivery"] == "not_sent"


# ═══ 2. доставка ≠ «ещё не доставлял» ≠ «опубликовано» ═══════════════════════

def test_delivery_axis_reads_not_delivered_with_exact_reason(
        tmp_path, monkeypatch):
    """После закрытия без отправки ось доставки — `not_delivered` + код.

    Мутация M3 (не применять факт закрытия попытки): ось снова «ещё не
    доставлял» — потеря снова невидима, тест красный.
    """
    monkeypatch.setenv("MEME_PENDING_DIR", str(tmp_path / "pending"))
    _stub_gates(monkeypatch)

    async def scenario():
        svc, ledger, _store = await _open(tmp_path, "delivery_axis.db")
        try:
            before = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            await _auto_pass(svc, ledger, sender=None)
            after = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS)
            return before["meme"]["last_delivery"], after["meme"]["last_delivery"]
        finally:
            await svc.close()

    before, after = asyncio.run(scenario())

    assert before["status"] == diag.DELIVERY_NEVER
    assert before["reason_code"] == ""
    assert after["status"] == diag.DELIVERY_NOT_DELIVERED
    assert after["reason_code"] == "publisher_not_bound"
    assert after["at"] == NOW_TS
    assert after["destination"] == CHAT
    assert after["message_id"] is None                  # изображение ≠ отправка
    assert set(after) == set(diag.LAST_DELIVERY_FIELDS)


def test_confirmed_delivery_wins_over_a_later_blocked_attempt(
        tmp_path, monkeypatch):
    """Подтверждённая отправка не переписывается отказом следующей попытки."""
    monkeypatch.setenv("MEME_PENDING_DIR", str(tmp_path / "pending"))
    _stub_gates(monkeypatch)

    async def scenario():
        svc, ledger, _store = await _open(tmp_path, "delivery_confirmed.db")
        try:
            sender = _Sender(message_id=4242)
            first = await _auto_pass(svc, ledger, sender=sender)
            # Второй проход: кулдаун истёк, отправителя нет.
            second = await _auto_pass(svc, ledger, sender=None,
                                      now_ts=NOW_TS + 7200)
            view = await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS + 7200)
            return first, second, view["meme"]["last_delivery"], sender
        finally:
            await svc.close()

    first, second, delivery, sender = asyncio.run(scenario())

    assert first.published is True and len(sender.calls) == 1
    assert second.published is False
    assert delivery["status"] == diag.DELIVERY_CONFIRMED
    assert delivery["message_id"] == 4242


# ═══ 3. квота: израсходовано ≠ отправлено ════════════════════════════════════

def test_quota_slot_stays_spent_and_is_shown_as_not_delivered(
        tmp_path, monkeypatch):
    """Слот не возвращается (вызов оплачен), но и не выдаётся за публикацию."""
    monkeypatch.setenv("MEME_PENDING_DIR", str(tmp_path / "pending"))
    _stub_gates(monkeypatch)

    async def scenario():
        svc, ledger, _store = await _open(tmp_path, "quota.db")
        try:
            await _auto_pass(svc, ledger, sender=None)
            view = meme.quota_view(ledger, chat_id=CHAT, day=_day(), limit=3)
            block = (await diag.collect_mechanism_diagnostics(
                svc, CHAT, now=NOW_TS))["meme"]["quota"]
            return view, block
        finally:
            await svc.close()

    view, block = asyncio.run(scenario())

    # Списание осталось прежним: вызов провайдера был настоящим.
    assert view["spent"] == 1
    assert view["limit"] == 3 and view["remaining"] == 2
    assert view["delivered"] == 0
    assert view["not_delivered"] == 1
    assert view["not_delivered_reasons"] == {"publisher_not_bound": 1}
    # Витрина показывает те же числа и не смешивает их с «использовано».
    assert (block["used"], block["delivered"], block["not_delivered"]) == (
        1, 0, 1)
    assert block["not_delivered_reasons"] == {"publisher_not_bound": 1}
    assert set(block) == set(diag.QUOTA_FIELDS)


def test_quota_slot_becomes_delivered_after_the_deferred_send(
        tmp_path, monkeypatch):
    """Поздняя доставка пересчитывает слот в «отправлено», списание — нет."""
    monkeypatch.setenv("MEME_PENDING_DIR", str(tmp_path / "pending"))
    _stub_gates(monkeypatch)

    async def scenario():
        svc, ledger, _store = await _open(tmp_path, "quota_late.db")
        try:
            await _auto_pass(svc, ledger, sender=None)
            before = meme.quota_view(ledger, chat_id=CHAT, day=_day(), limit=3)
            sender = _Sender(message_id=5150)
            await _tick(svc, ledger, sender=sender)
            after = meme.quota_view(ledger, chat_id=CHAT, day=_day(), limit=3)
            return before, after, sender
        finally:
            await svc.close()

    before, after, sender = asyncio.run(scenario())

    assert (before["spent"], before["delivered"],
            before["not_delivered"]) == (1, 0, 1)
    assert len(sender.calls) == 1
    assert after["spent"] == 1                       # квота не «возвращается»
    assert after["delivered"] == 1
    assert after["not_delivered"] == 0
    assert after["not_delivered_reasons"] == {}


# ═══ 4. durable-механизм переживает рестарт процесса ═════════════════════════

def test_deferred_row_waits_for_publisher_and_is_delivered_after_restart(
        tmp_path, monkeypatch):
    """Тик без отправителя → ожидание; после «рестарта» — ровно одна отправка.

    Мутация M2 (терминал вместо ожидания при `sender is None`): файл и строка
    исчезают на первом же тике, доставки после рестарта нет — тест красный.
    """
    pending = tmp_path / "pending"
    monkeypatch.setenv("MEME_PENDING_DIR", str(pending))
    db_path = tmp_path / "restart.db"

    async def scenario():
        svc, ledger, _store = await _open(tmp_path, "restart.db")
        try:
            await _auto_pass(svc, ledger, sender=None)
        finally:
            await svc.close()
        # ── тик без отправителя: ждём, ничего не теряем ──────────────────
        svc2 = DatabaseService(str(db_path))
        await svc2.initialize()
        ledger2 = meme.SqliteQuotaLedger(str(svc2.db_path))
        try:
            rows_before_wait = len(_attempts(ledger2))
            assert await _tick(svc2, ledger2, sender=None,
                               now_ts=NOW_TS + 30) == []
            rows_waiting = _deferred_rows(svc2)
            attempts_waiting = _attempts(ledger2)
            # Байты читаются ЗДЕСЬ: успешная доставка ниже их потребляет.
            waiting_bytes = Path(rows_waiting[0]["result_ref"]).read_bytes()
            waiting_path = Path(rows_waiting[0]["result_ref"])
        finally:
            await svc2.close()
        # ── «рестарт процесса»: новые объекты сервиса/журнала на том же файле
        svc3 = DatabaseService(str(db_path))
        await svc3.initialize()
        ledger3 = meme.SqliteQuotaLedger(str(svc3.db_path))
        try:
            sender = _Sender(message_id=7001)
            delivered = await _tick(svc3, ledger3, sender=sender,
                                    now_ts=NOW_TS + 60)
            return (rows_waiting, waiting_bytes, waiting_path,
                    attempts_waiting, rows_before_wait, sender, delivered,
                    _deferred_rows(svc3), _attempts(ledger3),
                    Path(rows_waiting[0]["result_ref"]))
        finally:
            await svc3.close()

    (rows_waiting, waiting_bytes, waiting_path, attempts_waiting,
     rows_before_wait, sender, delivered, rows_done, attempts_done,
     consumed) = asyncio.run(scenario())

    # Ожидание: строка жива, байты целы, новых строк журнала нет
    # (ожидание не является попыткой).
    assert len(rows_waiting) == 1
    assert rows_waiting[0]["status"] == JOB_QUEUED
    assert waiting_bytes == CONTENT
    assert len(attempts_waiting) == rows_before_wait
    # Доставка: ровно одна отправка тех же байтов и терминальная строка.
    assert len(sender.calls) == 1
    assert sender.calls[0][1] == CONTENT
    assert len(delivered) == 1 and delivered[0].published is True
    assert rows_done[0]["status"] == JOB_COMPLETED
    assert not consumed.exists()                           # байты потреблены
    assert not waiting_path.exists()
    terminal = max(attempts_done, key=lambda row: int(row.get("ts") or 0))
    assert terminal["outcome"] == "published"
    assert meme.parse_attempt_facts(terminal)["delivery"] == "sent"


def test_expired_deferred_row_closes_as_not_sent_instead_of_vanishing(
        tmp_path, monkeypatch):
    """Истёк срок → честный `deferred_publication_expired`, а не тихая потеря."""
    monkeypatch.setenv("MEME_PENDING_DIR", str(tmp_path / "pending"))
    cfg = _settings(cooldown_seconds=60)

    async def scenario():
        svc, ledger, _store = await _open(tmp_path, "expired.db")
        try:
            await _auto_pass(svc, ledger, sender=None, settings=cfg)
            sender = _Sender()
            # Тик позже ретенции: слот не освободился, отправителя нет.
            await _tick(svc, ledger, sender=sender, settings=cfg,
                        now_ts=NOW_TS + 61)
            return sender, _deferred_rows(svc), _attempts(ledger)
        finally:
            await svc.close()

    sender, rows, attempts = asyncio.run(scenario())

    assert sender.calls == []
    assert rows[0]["status"] == JOB_CANCELLED
    assert not Path(rows[0]["result_ref"]).exists()
    terminal = max(attempts, key=lambda row: int(row.get("ts") or 0))
    assert terminal["reason_code"] == meme.SKIP_DEFERRED_EXPIRED
    facts = meme.parse_attempt_facts(terminal)
    # Отложенный путь пишет факт доставки в факты этапа publish (ключ
    # `delivery`), а не в `publication`: это и читает ось доставки.
    assert facts["delivery"] == "not_sent"
