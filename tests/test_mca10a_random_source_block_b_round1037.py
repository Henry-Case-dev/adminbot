"""MCA-10a `mca-10a-random-source-anu` — focused-тесты блока B (T-4975).

Покрытие (A19/R3, spec §4–§6):
  * ANU-контракт: endpoint/header/params, типы/диапазоны/длина, hex+size;
  * origin-guard (не SSRF) и `redirect_blocked` без повторной отправки ключа;
  * 401/403 → `auth_failed` без цикла + circuit breaker/half-open;
  * 429 → `quota_exhausted` с Retry-After, min interval без запроса на
    каждое сообщение; timeout (sent=True) vs ConnectError (sent=False);
  * активация: реальная валидная партия → `quantum_activated` → active;
    HTTP 200 без валидации/mock/fallback ≠ активация; блокеры различимы;
    смена ключа → unverified, после исправления — сразу active;
  * квота: account-global (не per-chat), «оценка», unknown ≠ failed;
  * fallback: ON → PRNG + `random_fallback` один раз на переход; OFF →
    отложено с причиной, direct-путь жив (сеть не вызывается);
  * refill: watermark/buffer_max/K3 OFF; singleflight + durable task_jobs;
  * авто-возврат к quantum после восстановления провайдера.
"""
import asyncio

import httpx
import pytest

from services import mca_gates
from services import mca_random_source as mrs
from services.database import DatabaseService


@pytest.fixture(autouse=True)
def _clean_event_buffer():
    """Не оставлять события в глобальном bounded-буфере mca-13 между тестами."""
    mrs.mca_events.reset_pending()
    yield
    mrs.mca_events.reset_pending()


# ── fixtures/helpers ────────────────────────────────────────────────────────
async def _fresh_db(tmp_path, name="mca10a_b.db") -> DatabaseService:
    db = DatabaseService(str(tmp_path / name))
    await db.initialize()
    return db


@pytest.fixture
def mem(monkeypatch):
    values: dict = {}

    async def fake(key, chat_id, default):
        return values.get(key, default)

    monkeypatch.setattr(mrs, "_read_memory_setting", fake)
    return values


@pytest.fixture
def cfg(monkeypatch):
    values: dict = {"keys.random_quantum_batch_length": 8}

    def fake(key, default):
        return values.get(key, default)

    monkeypatch.setattr(mrs, "_hot_setting", fake)
    return values


@pytest.fixture
def events(monkeypatch):
    captured: list = []

    def fake_emit(event_name, *, outcome, **fields):
        captured.append({"event_name": event_name, "outcome": outcome,
                         **fields})
        return {}

    monkeypatch.setattr(mrs.mca_events, "emit_mca_event", fake_emit)
    return captured


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


def make_http(responses, calls=None, delay=0.0):
    """Управляемый http_get: очередь (status, headers, text) | Exception."""
    calls = calls if calls is not None else []

    async def http_get(url, headers, params, timeout):
        calls.append({"url": url, "headers": dict(headers),
                      "params": dict(params), "timeout": timeout})
        if delay:
            await asyncio.sleep(delay)
        item = responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        status, hdrs, text = item
        return mrs._HttpResponse(status=status, headers=hdrs, text=text)

    return http_get, calls


def ok_uint16(length: int, start: int = 0):
    return (200, {}, '{"success": true, "type": "uint16", "length": %d, '
                     '"data": %s}' % (length, list(range(start, start + length))))


def make_service(db, cfg, *, responses=None, clock=None, min_interval=0.0,
                 circuit_fails=3, cooldown=60.0, auto_refill=False,
                 delay=0.0):
    calls: list = []
    client = mrs.AnuClient(
        http_get=make_http(responses, calls, delay=delay)[0],
        min_interval=min_interval, circuit_fails=circuit_fails,
        circuit_cooldown=cooldown, clock=clock or FakeClock())
    svc = mrs.RandomSourceService(db, client=client,
                                  auto_refill=auto_refill)
    return svc, calls


# ── origin-guard / контракт клиента ─────────────────────────────────────────
def test_validate_endpoint_guard():
    assert mrs.validate_endpoint(mrs.ANU_ENDPOINT) == mrs.ANU_ENDPOINT
    assert mrs.validate_endpoint(mrs.ANU_ENDPOINT + "/") == mrs.ANU_ENDPOINT
    bad = [
        ("http://api.quantumnumbers.anu.edu.au", "scheme_not_allowed"),
        ("ftp://api.quantumnumbers.anu.edu.au", "scheme_not_allowed"),
        ("https://evil.example.com", "invalid_url"),
        ("https://api.quantumnumbers.anu.edu.au.evil.com", "invalid_url"),
        ("https://user:pass@api.quantumnumbers.anu.edu.au", "invalid_url"),
        ("https://api.quantumnumbers.anu.edu.au:8443", "invalid_url"),
        ("https://api.quantumnumbers.anu.edu.au/v1", "invalid_url"),
        ("https://api.quantumnumbers.anu.edu.au?x=1", "invalid_url"),
        ("", "invalid_url"),
    ]
    for url, code in bad:
        with pytest.raises(mrs.AnuError) as exc:
            mrs.validate_endpoint(url)
        assert exc.value.code == code, url


@pytest.mark.asyncio
async def test_client_contract_uint16_success():
    http_get, calls = make_http([ok_uint16(3)])
    client = mrs.AnuClient(http_get=http_get, min_interval=0.0,
                           clock=FakeClock())
    batch = await client.fetch(key="secret-key-1", length=3,
                               data_type="uint16")
    assert batch.values == [0, 1, 2] and batch.data_type == "uint16"
    assert len(calls) == 1
    assert calls[0]["url"] == mrs.ANU_ENDPOINT
    assert calls[0]["headers"] == {"x-api-key": "secret-key-1"}
    assert calls[0]["params"] == {"length": 3, "type": "uint16"}
    assert "secret-key-1" not in calls[0]["url"]


@pytest.mark.asyncio
async def test_client_hex_size_only_for_hex():
    http_get, calls = make_http([
        (200, {}, '{"success": true, "type": "hex8", "length": 2, '
                  '"data": ["00ff", "abcd"]}')])
    client = mrs.AnuClient(http_get=http_get, min_interval=0.0,
                           clock=FakeClock())
    batch = await client.fetch(key="k", length=2, data_type="hex8", size=2)
    assert batch.values == [255, 43981]
    assert calls[0]["params"] == {"length": 2, "type": "hex8", "size": 2}
    # size для uint-типа отвергается ДО запроса
    http_get2, calls2 = make_http([])
    client2 = mrs.AnuClient(http_get=http_get2, min_interval=0.0,
                            clock=FakeClock())
    with pytest.raises(mrs.AnuError) as exc:
        await client2.fetch(key="k", length=2, data_type="uint8", size=2)
    assert exc.value.code == "validation_failed" and calls2 == []


@pytest.mark.asyncio
async def test_client_validation_failures():
    key = "test-key-abc123"
    cases = [
        (200, '{"success": false, "error": "bad key %s"}' % key,
         "validation_failed"),
        (200, '{"success": true, "type": "uint8", "length": 2, '
              '"data": [1, 2]}', "validation_failed"),
        (200, '{"success": true, "type": "uint16", "length": 3, '
              '"data": [1, 2]}', "validation_failed"),
        (200, '{"success": true, "type": "uint16", "length": 2, '
              '"data": [1, 70000]}', "validation_failed"),
        (200, '{"success": true, "type": "uint16", "length": 2, '
              '"data": [1, "x"]}', "validation_failed"),
        (200, "not json", "validation_failed"),
    ]
    for status, text, code in cases:
        http_get, calls = make_http([(status, {}, text)])
        client = mrs.AnuClient(http_get=http_get, min_interval=0.0,
                               clock=FakeClock())
        with pytest.raises(mrs.AnuError) as exc:
            await client.fetch(key=key, length=2, data_type="uint16")
        assert exc.value.code == code
        assert len(calls) == 1 and exc.value.sent is True
    # ключ замаскирован в очищенной причине
    http_get, _ = make_http([(200, {}, '{"success": false, "error": "bad '
                                        'key %s"}' % key)])
    client = mrs.AnuClient(http_get=http_get, min_interval=0.0,
                           clock=FakeClock())
    with pytest.raises(mrs.AnuError) as exc:
        await client.fetch(key=key, length=2, data_type="uint16")
    assert key not in exc.value.reason and "***" in exc.value.reason


@pytest.mark.asyncio
async def test_client_redirect_blocked_no_key_resend():
    http_get, calls = make_http([
        (302, {"Location": "https://evil.example.com"}, "")])
    client = mrs.AnuClient(http_get=http_get, min_interval=0.0,
                           clock=FakeClock())
    with pytest.raises(mrs.AnuError) as exc:
        await client.fetch(key="secret-key", length=2, data_type="uint16")
    assert exc.value.code == "redirect_blocked"
    assert len(calls) == 1      # ключ повторно не отправлен


@pytest.mark.asyncio
async def test_client_401_no_loop_and_circuit_breaker():
    clock = FakeClock()
    http_get, calls = make_http([
        (401, {}, ""), (401, {}, ""), (401, {}, ""), ok_uint16(2)])
    client = mrs.AnuClient(http_get=http_get, min_interval=0.0,
                           circuit_fails=3, circuit_cooldown=60.0,
                           clock=clock)
    for wait in (0.0, 2.0, 4.0):     # backoff между провалами (2, 4)
        clock.advance(wait)
        with pytest.raises(mrs.AnuError) as exc:
            await client.fetch(key="k", length=2, data_type="uint16")
        assert exc.value.code == "auth_failed"
    # breaker open: четвёртый вызов — без HTTP-запроса (нет цикла)
    with pytest.raises(mrs.AnuError) as exc:
        await client.fetch(key="k", length=2, data_type="uint16")
    assert exc.value.code == "provider_unavailable"
    assert len(calls) == 3
    # half-open: после cooldown ровно один probe, успех закрывает breaker
    clock.advance(61)
    batch = await client.fetch(key="k", length=2, data_type="uint16")
    assert batch.values == [0, 1] and len(calls) == 4
    assert client.status()["fails"] == 0


@pytest.mark.asyncio
async def test_client_429_retry_after_and_min_interval():
    clock = FakeClock()
    http_get, calls = make_http([
        (429, {"Retry-After": "30"}, ""), ok_uint16(2)])
    client = mrs.AnuClient(http_get=http_get, min_interval=0.0,
                           circuit_fails=5, clock=clock)
    with pytest.raises(mrs.AnuError) as exc:
        await client.fetch(key="k", length=2, data_type="uint16")
    assert exc.value.code == "quota_exhausted"
    assert exc.value.retry_after == 30
    # без запроса на каждое сообщение: backoff/Retry-After держит интервал
    with pytest.raises(mrs.AnuError) as exc:
        await client.fetch(key="k", length=2, data_type="uint16")
    assert exc.value.code == "rate_limit" and exc.value.sent is False
    assert len(calls) == 1
    clock.advance(31)
    batch = await client.fetch(key="k", length=2, data_type="uint16")
    assert batch.values == [0, 1] and len(calls) == 2
    # min interval (Trial 1 req/s) — второй запрос в ту же секунду не уходит
    clock2 = FakeClock()
    http_get2, calls2 = make_http([ok_uint16(2), ok_uint16(2)])
    client2 = mrs.AnuClient(http_get=http_get2, min_interval=1.0,
                            clock=clock2)
    await client2.fetch(key="k", length=2, data_type="uint16")
    with pytest.raises(mrs.AnuError) as exc:
        await client2.fetch(key="k", length=2, data_type="uint16")
    assert exc.value.code == "rate_limit" and len(calls2) == 1
    clock2.advance(1.0)
    await client2.fetch(key="k", length=2, data_type="uint16")
    assert len(calls2) == 2


@pytest.mark.asyncio
async def test_client_timeout_sent_vs_connect_error_not_sent():
    http_get, _ = make_http([asyncio.TimeoutError()])
    client = mrs.AnuClient(http_get=http_get, min_interval=0.0,
                           clock=FakeClock())
    with pytest.raises(mrs.AnuError) as exc:
        await client.fetch(key="k", length=2, data_type="uint16")
    assert exc.value.code == "timeout" and exc.value.sent is True
    http_get2, _ = make_http([httpx.ConnectError("refused")])
    client2 = mrs.AnuClient(http_get=http_get2, min_interval=0.0,
                            clock=FakeClock())
    with pytest.raises(mrs.AnuError) as exc2:
        await client2.fetch(key="k", length=2, data_type="uint16")
    assert exc2.value.code == "provider_unavailable"
    assert exc2.value.sent is False


# ── активация/блокеры ───────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_activation_real_batch_quantum_activated(tmp_path, cfg, mem,
                                                       events):
    db = await _fresh_db(tmp_path)
    try:
        cfg[mrs.SETTING_KEY] = "anu-key-A"
        svc, calls = make_service(db, cfg, responses=[ok_uint16(8)])
        result = await svc.activate()
        assert result["activated"] is True and result["state"] == "active"
        assert result["batch_id"] and result["length"] == 8
        assert await svc.anu_state() == "active"
        state = await svc._store.get_state()
        assert state["key_fingerprint"] == mrs.key_fingerprint("anu-key-A")
        assert state["activation_batch_id"] == result["batch_id"]
        assert state["activated_at"]
        # self-check через адаптер израсходовал одно значение
        assert await svc._store.reserve_remaining() == 7
        rows = await svc.recent_draws(limit=5)
        assert any(r["purpose"] == "activation_selfcheck" for r in rows)
        activations = [e for e in events if e["event_name"] ==
                       "random_activation"]
        assert len(activations) == 1
        assert activations[0]["outcome"] == "success"
        assert activations[0]["reason_code"] == "quantum_activated"
        assert len(calls) == 1
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_activation_http200_without_valid_content_not_activation(
        tmp_path, cfg, mem, events):
    db = await _fresh_db(tmp_path)
    try:
        cfg[mrs.SETTING_KEY] = "anu-key-A"
        svc, _ = make_service(db, cfg, responses=[
            (200, {}, '{"success": false, "error": "quota"}')])
        result = await svc.activate()
        assert result["activated"] is False
        assert result["blocker"] == "validation_failed"
        assert await svc.anu_state() != "active"
        assert await svc._store.reserve_remaining() == 0
        failed = [e for e in events if e["event_name"] == "random_activation"]
        assert failed and failed[0]["outcome"] == "failed"
        assert failed[0]["reason_code"] == "validation_failed"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_activation_no_key_blocker_visible(tmp_path, cfg, mem, events):
    db = await _fresh_db(tmp_path)
    try:
        svc, calls = make_service(db, cfg, responses=[])
        result = await svc.activate()
        assert result["state"] == "provider_unconfigured"
        assert result["blocker"] == "provider_unconfigured"
        assert calls == []      # запрос не выполнялся
        failed = [e for e in events if e["event_name"] == "random_activation"]
        assert failed and failed[0]["reason_code"] == "provider_unconfigured"
        snapshot = await svc.status_snapshot(chat_id=1)
        assert snapshot["anu_state"] == "provider_unconfigured"
        assert snapshot["key_present"] is False
        assert snapshot["effective_source"] == "pseudorandom"
        assert snapshot["fallback_reason"] == "provider_unconfigured"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_key_change_unverified_then_immediate_activation(
        tmp_path, cfg, mem, events):
    db = await _fresh_db(tmp_path)
    try:
        cfg[mrs.SETTING_KEY] = "anu-key-A"
        clock = FakeClock()
        svc, _ = make_service(db, cfg, clock=clock, responses=[
            ok_uint16(8), (401, {}, ""), ok_uint16(8)])
        assert (await svc.activate())["activated"] is True
        cfg[mrs.SETTING_KEY] = "anu-key-B"
        assert await svc.anu_state() == "unverified"   # неизвестный ключ
        result = await svc.activate()
        assert result["activated"] is False
        assert result["blocker"] == "auth_failed"
        assert await svc.anu_state() == "unverified"
        # после исправления ключа — активация сразу, без релиза
        clock.advance(2.0)      # backoff после 401 (не цикл)
        assert (await svc.activate())["activated"] is True
        assert await svc.anu_state() == "active"
        outcomes = [e["reason_code"] for e in events
                    if e["event_name"] == "random_activation"]
        assert outcomes == ["quantum_activated", "auth_failed",
                            "quantum_activated"]
    finally:
        await db.close()


# ── квота ───────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_quota_global_estimate_not_per_chat(tmp_path, cfg, mem, events):
    db = await _fresh_db(tmp_path)
    try:
        cfg[mrs.SETTING_KEY] = "anu-key-A"
        svc, _ = make_service(db, cfg, responses=[ok_uint16(8)])
        await svc.activate(manual=True)
        await svc.draw_index(5, chat_id=1, purpose="p")
        await svc.draw_index(5, chat_id=2, purpose="p")
        snapshot = await svc.quota_snapshot()
        assert snapshot["account_key"] == "anu:trial"
        assert snapshot["manual_checks"] == 1
        assert snapshot["success"] == 1
        assert snapshot["failed"] == 0 and snapshot["unknown"] == 0
        assert snapshot["used"] == 2
        assert snapshot["limit"] == 100 and snapshot["remaining"] == 98
        assert snapshot["estimate"] is True
        # один аккаунт-ряд (не дублируется по чатам)
        cur = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_random_quota_state")
        assert (await cur.fetchone())["c"] == 1
        # Paid/Custom: локальный счётчик без «остатка»
        cfg[mrs.SETTING_PLAN] = "Paid"
        paid = await svc.quota_snapshot()
        assert paid["remaining"] is None and paid["limit"] is None
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_quota_period_rollover_honest_remaining(tmp_path, cfg, mem):
    """F-1 (review Medium): учёт квоты period-aware — после смены месяца
    «оценка» не залипает на исчерпании прошлого периода (spec §14.3/D3:
    account_key+period); 429/unknown-семантика не меняется."""
    db = await _fresh_db(tmp_path)
    try:
        svc = mrs.RandomSourceService(db, auto_refill=False)
        account = svc._account_key()
        # прошлый период: Trial-лимит исчерпан (100 записей)
        await db.db.execute(
            "INSERT INTO mca_random_quota_state (account_key, period, success,"
            " failed, unknown, manual_checks, last_success_at, last_failure_at,"
            " last_reason, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
            (account, "2000-01", 97, 2, 1, 0, 1, 1, "quota_exhausted", 1))
        await db.db.commit()
        snapshot = await svc.quota_snapshot()
        assert snapshot["period"] == mrs._utc_period()
        assert snapshot["used"] == 0          # счётчики прошлого месяца не переносятся
        assert snapshot["remaining"] == 100   # честная «оценка» нового периода
        assert snapshot["estimate"] is True
        assert snapshot["last_reason"] is None
        # запись в новом периоде сбрасывает старые счётчики и учитывает 429/unknown
        await svc._store.quota_record(account_key=account,
                                      period=mrs._utc_period(),
                                      outcome="failed", manual=True,
                                      reason="quota_exhausted")
        await svc._store.quota_record(account_key=account,
                                      period=mrs._utc_period(),
                                      outcome="success")
        fresh = await svc.quota_snapshot()
        assert fresh["period"] == mrs._utc_period()
        assert fresh["failed"] == 1 and fresh["unknown"] == 0
        assert fresh["success"] == 1 and fresh["manual_checks"] == 1
        assert fresh["used"] == 3
        assert fresh["remaining"] == 97
        assert fresh["last_reason"] == "quota_exhausted"   # 429 авторитетен
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_quota_timeout_unknown_and_connect_error_not_counted(
        tmp_path, cfg, mem):
    db = await _fresh_db(tmp_path)
    try:
        svc, _ = make_service(db, cfg, responses=[asyncio.TimeoutError()])
        result = await svc.test_connection(draft_key="draft-key-X")
        assert result["healthy"] is False and result["blocker"] == "timeout"
        snapshot = await svc.quota_snapshot()
        assert snapshot["unknown"] == 1 and snapshot["failed"] == 0
        assert snapshot["manual_checks"] == 1
        svc2, _ = make_service(db, cfg, responses=[httpx.ConnectError("x")])
        result2 = await svc2.test_connection(draft_key="draft-key-Y")
        assert result2["healthy"] is False
        assert result2["blocker"] == "provider_unavailable"
        snapshot2 = await svc2.quota_snapshot()
        # ConnectError — запрос не ушёл: квота не растёт (used = timeout-запись)
        assert snapshot2["used"] == 2 and snapshot2["failed"] == 0
        assert snapshot2["unknown"] == 1
    finally:
        await db.close()


# ── fallback / отсутствие зависания ─────────────────────────────────────────
@pytest.mark.asyncio
async def test_fallback_on_transition_event_once_and_recovery(tmp_path, mem,
                                                              cfg, events):
    db = await _fresh_db(tmp_path)
    try:
        svc, calls = make_service(db, cfg, responses=[])
        first = await svc.draw_index(10, chat_id=1, purpose="p")
        second = await svc.draw_index(10, chat_id=1, purpose="p")
        assert first.source == "pseudorandom" and second.source == "pseudorandom"
        assert first.fallback_reason == "provider_unconfigured"
        assert calls == []      # чат не ждёт сеть — draw локальный
        fallbacks = [e for e in events if e["event_name"] == "random_fallback"]
        assert len(fallbacks) == 1      # один раз на переход, не на draw
        assert fallbacks[0]["reason_code"] == "random_fallback"
        snapshot = await svc.status_snapshot(chat_id=1)
        assert snapshot["effective_source"] == "pseudorandom"
        assert snapshot["last_fallback_reason"] == "provider_unconfigured"
        # восстановление: реальная партия → quantum; затем исчерпание → снова
        # один notable-переход
        await svc._store.insert_batch(mrs.AnuBatch(
            values=[7, 8, 9, 10, 11], data_type="uint16", length=5))
        quantum = await svc.draw_index(3, chat_id=1, purpose="p")
        assert quantum.source == "quantum" and quantum.index == 7 % 3
        assert (await svc.status_snapshot(chat_id=1))["effective_source"] == \
            "quantum"
        for _ in range(4):      # исчерпать остаток партии
            more = await svc.draw_index(3, chat_id=1, purpose="p")
            assert more.source == "quantum"
        again = await svc.draw_index(3, chat_id=1, purpose="p")
        assert again.source == "pseudorandom"
        fallbacks = [e for e in events if e["event_name"] == "random_fallback"]
        assert len(fallbacks) == 2
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_fallback_off_defers_with_reason_direct_path_alive(
        tmp_path, mem, cfg, events):
    db = await _fresh_db(tmp_path)
    try:
        mem[mrs.SETTING_FALLBACK] = False
        svc, calls = make_service(db, cfg, responses=[])
        result = await svc.draw_index(10, chat_id=1, purpose="p")
        assert result.deferred is True and result.index is None
        assert result.reason == "provider_unconfigured"
        assert calls == []      # сеть не вызывается; прямой путь не блокируется
        assert await svc.recent_draws(limit=5) == []
        fallbacks = [e for e in events if e["event_name"] == "random_fallback"]
        assert len(fallbacks) == 1
        assert fallbacks[0]["reason_code"] == "provider_unconfigured"
    finally:
        await db.close()


# ── refill ──────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_refill_watermark_buffer_and_gates(tmp_path, cfg, mem):
    db = await _fresh_db(tmp_path)
    try:
        cfg[mrs.SETTING_KEY] = "anu-key-A"
        svc, calls = make_service(db, cfg, responses=[])
        await svc._store.insert_batch(mrs.AnuBatch(
            values=list(range(300)), data_type="uint16", length=300))
        result = await svc.refill_if_needed()
        assert result["status"] == "skipped"
        assert result["reason"] == "watermark_ok"
        assert calls == []
        await svc._store.insert_batch(mrs.AnuBatch(
            values=list(range(2048)), data_type="uint16", length=2048))
        result = await svc.refill_if_needed()
        assert result["reason"] == "buffer_full" and calls == []
        # K3 OFF → refill не запускается (запас только расходуется)
        db2 = await _fresh_db(tmp_path, name="mca10a_b2.db")
        svc2, calls2 = make_service(db2, cfg, responses=[])
        monkey = None
        try:
            import services.mca_gates as gates
            monkey = gates.random_refill_enabled
            gates.random_refill_enabled = lambda: False
            assert (await svc2.refill_if_needed())["status"] == "disabled"
            assert calls2 == []
        finally:
            if monkey is not None:
                gates.random_refill_enabled = monkey
            await db2.close()
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_refill_singleflight_durable_job(tmp_path, cfg, mem, events):
    db = await _fresh_db(tmp_path)
    try:
        cfg[mrs.SETTING_KEY] = "anu-key-A"
        svc, calls = make_service(db, cfg, responses=[ok_uint16(8)],
                                  delay=0.2)
        task1 = asyncio.create_task(svc.refill_if_needed())
        await asyncio.sleep(0.05)
        second = await svc.refill_if_needed()
        await task1
        assert len(calls) == 1                  # singleflight: один запрос
        cur = await db.db.execute(
            "SELECT COUNT(*) AS c FROM mca_random_batches")
        assert (await cur.fetchone())["c"] == 1
        cur = await db.db.execute(
            "SELECT owner, kind FROM task_jobs WHERE owner = 'random.source'")
        jobs = [tuple(r) for r in await cur.fetchall()]
        assert jobs and all(j[1] == "refill" for j in jobs)
        assert await svc.anu_state() == "active"   # валидная партия → активация
        assert await svc._store.reserve_remaining() == 7
        assert second["status"] in ("completed", "running")
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_auto_return_to_quantum_after_recovery(tmp_path, cfg, mem,
                                                    events):
    db = await _fresh_db(tmp_path)
    try:
        cfg[mrs.SETTING_KEY] = "anu-key-A"
        cfg[mrs.SETTING_BATCH_LENGTH] = 16
        svc, _ = make_service(db, cfg, responses=[ok_uint16(16)])
        mrs.reset_service()
        mrs._service = svc
        src_before = await mrs.for_dream(1, k_hint=2, chat_id=1)
        assert src_before.source == "pseudorandom"
        assert src_before.fallback is True
        await svc.refill_if_needed(force=True)
        assert (await svc.status_snapshot(chat_id=1))["effective_source"] == \
            "quantum"       # авто-возврат: запас снова непуст
        src_after = await mrs.for_dream(1, k_hint=2, chat_id=1)
        assert src_after.source == "quantum" and src_after.fallback is False
    finally:
        mrs.reset_service()
        await db.close()
