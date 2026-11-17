"""QRNG P2 — LfDR-адаптер (arch-decision 2026-11-17 D9, `QAN-REC-LFDR-01`).

Инварианты P2:
  * документированный публичный endpoint (`https://lfdr.de/qrng_api/qrng`,
    GET, `length` + `format=HEX`); произвольный endpoint/userinfo/порт/путь/
    query/redirect отвергаются origin-guard'ом ДО запроса;
  * ответ `{"length": N, "qrn": "<2N hex>"}`: длина/чётность/символы/схема
    проверяются, HEX→uint8, партия — существующий `AnuBatch` с provider `lfdr`;
  * ключа нет: ни поля ключа, ни заголовков авторизации (requires_key=False);
  * ошибки/таймаут/429/5xx/битый JSON → честные коды; circuit breaker и
    min-interval — существующая семантика, отдельное состояние от ANU;
  * реестр `PROVIDERS` содержит `lfdr` с `entropy_class=hardware_quantum`
    и точками входа fetch/check; IBM остаётся без адаптера (P5);
  * Lizaonair отсутствует (EXC-01…05); ANU-клиент/guard не изменены.
"""
import asyncio
import json
from pathlib import Path

import pytest

from services import mca_random_source as mrs

LFDR_OK = (200, {}, json.dumps({"length": 2, "qrn": "5ef1"}))


class FakeClock:
    def __init__(self, start: float = 1000.0):
        self.now = float(start)

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += float(seconds)


class ConnectTimeout(Exception):
    """Похоже на httpx.ConnectTimeout по имени (запрос не ушёл)."""


def make_http(responses, calls=None):
    calls = calls if calls is not None else []

    async def http_get(url, headers, params, timeout):
        calls.append({"url": url, "headers": dict(headers),
                      "params": dict(params), "timeout": timeout})
        item = responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        status, hdrs, text = item
        return mrs._HttpResponse(status=status, headers=hdrs, text=text)

    return http_get, calls


def hex_payload(length: int, qrn: str):
    return (200, {}, json.dumps({"length": length, "qrn": qrn}))


def make_client(responses, *, calls=None, clock=None, min_interval=0.0,
                timeout=5.0, circuit_fails=3, circuit_cooldown=60.0):
    http_get, calls = make_http(responses, calls)
    client = mrs.LfdrClient(
        http_get=http_get, timeout=timeout, min_interval=min_interval,
        circuit_fails=circuit_fails, circuit_cooldown=circuit_cooldown,
        clock=clock or FakeClock())
    return client, calls


# ── реестр: lfdr без ключа, с адаптером; IBM без адаптера ───────────────────
class TestRegistry:
    def test_lfdr_registered_hardware_keyless_with_hooks(self):
        assert set(mrs.PROVIDERS) == {
            mrs.PROVIDER_ID_IBM, mrs.PROVIDER_ID_ANU, mrs.PROVIDER_ID_LFDR}
        spec = mrs.PROVIDERS[mrs.PROVIDER_ID_LFDR]
        assert spec.id == "lfdr" and spec.title == "LfDR QRNG"
        assert spec.entropy_class == mrs.ENTROPY_CLASS_HARDWARE
        assert spec.requires_key is False
        assert spec.key_setting is None          # поля ключа нет
        assert callable(spec.fetch) and callable(spec.check)
        assert spec.fetch is mrs.lfdr_fetch
        assert spec.check is mrs.lfdr_check
        # P5 не реализован: IBM по-прежнему без адаптера (без фейкового green).
        assert mrs.PROVIDERS[mrs.PROVIDER_ID_IBM].fetch is None
        assert mrs.PROVIDERS[mrs.PROVIDER_ID_IBM].check is None
        # entropy_class производный, а не дюжина отдельных констант
        assert all(p.entropy_class == "hardware_quantum"
                   for p in mrs.PROVIDERS.values())

    def test_no_lfdr_api_key_setting_or_header(self):
        assert len(mrs.PROVIDER_KEY_SETTINGS) == 9
        assert not any("lfdr" in key.lower()
                       for key in mrs.PROVIDER_KEY_SETTINGS)
        source = Path(mrs.__file__).read_text(encoding="utf-8").lower()
        for forbidden in ("lfdr_api_key", "keys.lfdr", "random_lfdr"):
            assert forbidden not in source
        assert "lizaonair" not in source
        assert mrs.canonical_provider_id("lizaonair") == ""
        assert mrs.canonical_provider_id("lfdr") == "lfdr"

    def test_lfdr_constants_match_documented_contract(self):
        assert mrs.LFDR_HOST == "lfdr.de"
        assert mrs.LFDR_PATH == "/qrng_api/qrng"
        assert mrs.LFDR_ENDPOINT == "https://lfdr.de/qrng_api/qrng"
        assert mrs.LFDR_FORMAT == "HEX"
        assert mrs.LFDR_MIN_LENGTH == 1
        # безопасный предел = действующий контракт партии, не 2^31 провайдера
        assert mrs.LFDR_MAX_LENGTH == mrs.MAX_LENGTH == 1024


# ── origin-guard ────────────────────────────────────────────────────────────
class TestOriginGuard:
    def test_accepts_only_documented_endpoint(self):
        assert mrs.validate_lfdr_endpoint(mrs.LFDR_ENDPOINT) == mrs.LFDR_ENDPOINT
        assert mrs.validate_lfdr_endpoint(
            "https://lfdr.de:443/qrng_api/qrng") == mrs.LFDR_ENDPOINT
        assert mrs.validate_lfdr_endpoint(
            "https://LFDR.DE/qrng_api/qrng") == mrs.LFDR_ENDPOINT

    @pytest.mark.parametrize("url,code", [
        ("http://lfdr.de/qrng_api/qrng", "scheme_not_allowed"),
        ("ftp://lfdr.de/qrng_api/qrng", "scheme_not_allowed"),
        ("https://evil.example.com/qrng_api/qrng", "invalid_url"),
        ("https://lfdr.de.evil.example.com/qrng_api/qrng", "invalid_url"),
        ("https://evil-lfdr.de/qrng_api/qrng", "invalid_url"),
        ("https://user:pass@lfdr.de/qrng_api/qrng", "invalid_url"),
        ("https://lfdr.de:8443/qrng_api/qrng", "invalid_url"),
        ("https://lfdr.de/qrng", "invalid_url"),
        ("https://lfdr.de/qrng_api/qrng/", "invalid_url"),
        ("https://lfdr.de/qrng_api/qrng/x", "invalid_url"),
        ("https://lfdr.de/qrng_api/qrng?length=1&format=HEX", "invalid_url"),
        ("https://lfdr.de/qrng_api/qrng#frag", "invalid_url"),
        ("", "invalid_url"),
    ])
    def test_rejects_arbitrary_endpoint(self, url, code):
        with pytest.raises(mrs.AnuError) as exc:
            mrs.validate_lfdr_endpoint(url)
        assert exc.value.code == code, url
        assert exc.value.sent is False

    @pytest.mark.asyncio
    async def test_guard_runs_before_any_request(self):
        client, calls = make_client([])
        for url in ("http://lfdr.de/qrng_api/qrng",
                    "https://lfdr.de/qrng",
                    "https://user@lfdr.de/qrng_api/qrng"):
            with pytest.raises(mrs.AnuError):
                await client.fetch(length=2, endpoint=url)
        assert calls == []

    def test_guards_of_both_providers_are_separate(self):
        # ANU-guard не принимает LfDR, LfDR-guard не принимает ANU.
        with pytest.raises(mrs.AnuError):
            mrs.validate_endpoint("https://lfdr.de")
        with pytest.raises(mrs.AnuError):
            mrs.validate_lfdr_endpoint(mrs.ANU_ENDPOINT)
        assert mrs.validate_endpoint(mrs.ANU_ENDPOINT) == mrs.ANU_ENDPOINT


# ── контракт ответа: HEX → uint8, длина/символы/схема ──────────────────────
class TestFetchContract:
    @pytest.mark.asyncio
    async def test_valid_hex_to_uint8_and_request_shape(self):
        client, calls = make_client([hex_payload(3, "00ffAB")], timeout=7.0)
        batch = await client.fetch(length=3)
        assert batch.values == [0, 255, 171]
        assert batch.data_type == "uint8"
        assert batch.length == 3
        assert batch.provider == mrs.PROVIDER_ID_LFDR
        assert isinstance(batch.latency_ms, int) and batch.latency_ms >= 0
        assert len(calls) == 1
        assert calls[0]["url"] == "https://lfdr.de/qrng_api/qrng"
        assert calls[0]["params"] == {"length": 3, "format": "HEX"}
        assert calls[0]["headers"] == {}          # никакого ключа/токена
        assert calls[0]["timeout"] == 7.0

    @pytest.mark.asyncio
    async def test_string_length_field_accepted_and_uppercase_hex(self):
        client, _ = make_client([(200, {},
                                  '{"length": "4", "qrn": "DEADBEEF"}')])
        batch = await client.fetch(length=4)
        assert batch.values == [0xDE, 0xAD, 0xBE, 0xEF]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("payload,length", [
        ({"length": 3, "qrn": "aabbcc"}, 2),          # другой запрошенный N
        ({"length": 3, "qrn": "aabb"}, 2),            # length ≠ N при верном qrn
        ({"length": 2, "qrn": "aabbcc"}, 2),          # qrn длиннее N
        ({"length": 2, "qrn": "aab"}, 2),             # нечётное число символов
        ({"length": 2, "qrn": "zzzz"}, 2),            # не hex
        ({"length": 2, "qrn": "0x0x"}, 2),            # не hex
        ({"length": 2, "qrn": "   "}, 2),             # пробелы вместо hex
        ({"length": 2, "qrn": 123}, 2),               # не строка
        ({"length": 2, "qrn": None}, 2),              # null
        ({"length": True, "qrn": "aabb"}, 2),         # bool не длина
        ({"length": "2.0", "qrn": "aabb"}, 2),        # не целое
        ({"length": 2}, 2),                           # qrn отсутствует
        ({"qrn": "aabb"}, 2),                         # length отсутствует
        ([], 2),                                      # не объект
        ({"error": "Failed to read device"}, 2),      # error при 200
    ])
    async def test_invalid_payload_is_validation_failed(self, payload, length):
        client, calls = make_client([(200, {}, json.dumps(payload))])
        with pytest.raises(mrs.AnuError) as exc:
            await client.fetch(length=length)
        assert exc.value.code == "validation_failed"
        assert exc.value.sent is True and len(calls) == 1

    @pytest.mark.asyncio
    async def test_declared_length_digit_bomb_is_validation_failed(self):
        """F1: 4301-значная length-строка не роняет fetch сырым ValueError.

        CPython int-max-str-digits (4300) превращал `int(text)` в ValueError,
        который вылетал мимо контракта AnuError/LfdrError и не отмечал failure
        у breaker'а. Ожидание: `validation_failed`, fails=1, sent=True."""
        bomb = "9" * 4301
        payload = json.dumps({"length": bomb, "qrn": "aabb"})
        client, calls = make_client([(200, {}, payload)])
        with pytest.raises(mrs.AnuError) as exc:
            await client.fetch(length=2)
        assert isinstance(exc.value, mrs.LfdrError)
        assert exc.value.code == "validation_failed"
        assert exc.value.sent is True and len(calls) == 1
        assert client.status()["fails"] == 1
        # та же защита на пути проверки подключения (check не бросает)
        check_client, _ = make_client([(200, {}, payload)])
        result = await check_client.check()
        assert result["healthy"] is False
        assert result["blocker"] == "validation_failed"
        assert check_client.status()["fails"] == 1

    @pytest.mark.asyncio
    async def test_broken_json_is_validation_failed(self):
        client, calls = make_client([(200, {}, "not json")])
        with pytest.raises(mrs.AnuError) as exc:
            await client.fetch(length=2)
        assert exc.value.code == "validation_failed"
        assert exc.value.sent is True and len(calls) == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("bad_length", [0, -1, 1025, 4096, "abc", True,
                                            2.5, None])
    async def test_bounds_rejected_before_request(self, bad_length):
        client, calls = make_client([])
        with pytest.raises(mrs.AnuError) as exc:
            await client.fetch(length=bad_length)
        assert exc.value.code == "validation_failed"
        assert exc.value.sent is False
        assert calls == []                  # провайдер не вызывался

    @pytest.mark.asyncio
    async def test_max_length_boundary_accepted(self):
        qrn = "ab" * mrs.LFDR_MAX_LENGTH
        client, calls = make_client([hex_payload(mrs.LFDR_MAX_LENGTH, qrn)])
        batch = await client.fetch(length=mrs.LFDR_MAX_LENGTH)
        assert len(batch.values) == 1024
        assert set(batch.values) == {0xAB}
        assert calls[0]["params"]["length"] == 1024


# ── транспорт/HTTP-коды/таймауты ───────────────────────────────────────────
class TestTransportErrors:
    @pytest.mark.asyncio
    async def test_429_rate_limit_retry_after_then_backoff(self):
        clock = FakeClock()
        client, calls = make_client(
            [(429, {"Retry-After": "30"}, ""), LFDR_OK],
            clock=clock, circuit_fails=5)
        with pytest.raises(mrs.AnuError) as exc:
            await client.fetch(length=2)
        assert exc.value.code == "rate_limit"
        assert exc.value.retryable is True and exc.value.sent is True
        assert exc.value.retry_after == 30
        # backoff (max(2,Retry-After)): повтор без нового HTTP
        clock.advance(1)
        with pytest.raises(mrs.AnuError) as exc:
            await client.fetch(length=2)
        assert exc.value.code == "rate_limit" and len(calls) == 1
        clock.advance(31)
        batch = await client.fetch(length=2)
        assert batch.values == [0x5E, 0xF1] and len(calls) == 2

    @pytest.mark.asyncio
    async def test_5xx_provider_unavailable_retryable(self):
        client, calls = make_client(
            [(500, {}, '{"error": "Failed to open device"}')])
        with pytest.raises(mrs.AnuError) as exc:
            await client.fetch(length=2)
        assert exc.value.code == "provider_unavailable"
        assert exc.value.retryable is True and exc.value.sent is True
        assert "Failed to open device" in exc.value.reason

    @pytest.mark.asyncio
    async def test_4xx_client_error_not_retryable(self):
        client, _ = make_client(
            [(400, {}, '{"error": "length param out of bounds"}')])
        with pytest.raises(mrs.AnuError) as exc:
            await client.fetch(length=2)
        assert exc.value.code == "client_error"
        assert exc.value.retryable is False and exc.value.sent is True
        assert "out of bounds" in exc.value.reason

    @pytest.mark.asyncio
    async def test_redirect_blocked_single_request(self):
        client, calls = make_client(
            [(302, {"Location": "https://evil.example.com/"}, "")])
        with pytest.raises(mrs.AnuError) as exc:
            await client.fetch(length=2)
        assert exc.value.code == "redirect_blocked"
        assert len(calls) == 1          # redirect не выполняется

    @pytest.mark.asyncio
    async def test_401_auth_failed_honest(self):
        client, _ = make_client([(401, {}, "")])
        with pytest.raises(mrs.AnuError) as exc:
            await client.fetch(length=2)
        assert exc.value.code == "auth_failed"

    @pytest.mark.asyncio
    async def test_timeout_after_send_marks_sent(self):
        client, calls = make_client([asyncio.TimeoutError()])
        with pytest.raises(mrs.AnuError) as exc:
            await client.fetch(length=2)
        assert exc.value.code == "timeout"
        assert exc.value.sent is True and exc.value.retryable is True
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_connect_timeout_not_sent(self):
        client, _ = make_client([ConnectTimeout("connect")])
        with pytest.raises(mrs.AnuError) as exc:
            await client.fetch(length=2)
        assert exc.value.code == "timeout" and exc.value.sent is False

    @pytest.mark.asyncio
    async def test_min_interval_blocks_second_request(self):
        clock = FakeClock()
        client, calls = make_client([LFDR_OK, LFDR_OK], clock=clock,
                                    min_interval=2.0)
        await client.fetch(length=2)
        clock.advance(1)
        with pytest.raises(mrs.AnuError) as exc:
            await client.fetch(length=2)
        assert exc.value.code == "rate_limit" and exc.value.sent is False
        assert len(calls) == 1


# ── circuit breaker (существующая семантика, состояние отдельное) ──────────
class TestCircuitBreaker:
    @pytest.mark.asyncio
    async def test_three_failures_open_then_single_probe(self):
        clock = FakeClock()
        client, calls = make_client(
            [(500, {}, ""), (500, {}, ""), (500, {}, ""), LFDR_OK],
            clock=clock, circuit_fails=3, circuit_cooldown=60.0)
        for wait in (0.0, 2.0, 4.0):
            clock.advance(wait)
            with pytest.raises(mrs.AnuError) as exc:
                await client.fetch(length=2)
            assert exc.value.code == "provider_unavailable"
            assert exc.value.reason.startswith("http 500")
        # breaker open: четвёртый вызов — без HTTP
        with pytest.raises(mrs.AnuError) as exc:
            await client.fetch(length=2)
        assert exc.value.code == "provider_unavailable"
        assert exc.value.reason == "circuit_open"
        assert len(calls) == 3
        # half-open: ровно один probe, успех закрывает breaker
        clock.advance(61)
        batch = await client.fetch(length=2)
        assert batch.values == [0x5E, 0xF1]
        assert len(calls) == 4 and client.status()["fails"] == 0

    @pytest.mark.asyncio
    async def test_breaker_state_is_not_shared_with_anu(self):
        clock = FakeClock()
        lfdr, lfdr_calls = make_client(
            [(500, {}, ""), (500, {}, ""), (500, {}, "")],
            clock=clock, circuit_fails=3)
        for wait in (0.0, 2.0, 4.0):
            clock.advance(wait)
            with pytest.raises(mrs.AnuError):
                await lfdr.fetch(length=2)
        with pytest.raises(mrs.AnuError) as exc:
            await lfdr.fetch(length=2)
        assert exc.value.reason == "circuit_open" and len(lfdr_calls) == 3
        # ANU-клиент (другой инстанс/источник) не затронут
        anu_http, anu_calls = make_http([
            (200, {}, '{"success": true, "type": "uint16", "length": 2, '
                      '"data": [1, 2]}')])
        anu = mrs.AnuClient(http_get=anu_http, min_interval=0.0, clock=clock)
        batch = await anu.fetch(key="k", length=2, data_type="uint16")
        assert batch.values == [1, 2] and len(anu_calls) == 1


# ── реестровые точки входа + проверка подключения ──────────────────────────
class TestRegistryEntryPoints:
    @pytest.mark.asyncio
    async def test_lfdr_fetch_uses_shared_client(self):
        client, calls = make_client([LFDR_OK])
        batch = await mrs.lfdr_fetch(length=2, client=client)
        assert batch.values == [0x5E, 0xF1]
        assert batch.provider == "lfdr" and len(calls) == 1

    @pytest.mark.asyncio
    async def test_lfdr_fetch_one_shot_with_injected_http(self):
        http_get, calls = make_http([hex_payload(1, "03")])
        batch = await mrs.lfdr_fetch(length=1, http_get=http_get)
        assert batch.values == [3] and len(calls) == 1

    @pytest.mark.asyncio
    async def test_lfdr_check_success_has_no_raw_values(self):
        client, calls = make_client([hex_payload(1, "03")])
        result = await mrs.lfdr_check(client=client)
        assert result["healthy"] is True and result["blocker"] is None
        assert result["provider"] == "lfdr" and result["length"] == 1
        assert result["requires_key"] is False
        assert isinstance(result["latency_ms"], int)
        assert calls[0]["params"] == {"length": 1, "format": "HEX"}
        assert "qrn" not in result and "values" not in result

    @pytest.mark.asyncio
    async def test_lfdr_batch_consumed_by_existing_atomic_store(self, tmp_path):
        """AC-06: полученные значения расходуются существующим store.

        Новый store/очередь не создаются: партия едет в `mca_random_batches`
        через `insert_batch`, а `reserve_chunk`/`reserve_draw` выдают ровно
        проверенные uint8-значения с provider `lfdr`."""
        from services.database import DatabaseService

        db = DatabaseService(str(tmp_path / "qrng_p2_consume.db"))
        await db.initialize()
        try:
            http_get, _ = make_http([hex_payload(3, "00ff10")])
            batch = await mrs.lfdr_fetch(length=3, http_get=http_get)
            store = mrs.RandomStore(db)
            await store.insert_batch(batch)
            chunk = await store.reserve_chunk(3)
            assert [item.value for item in chunk] == [0, 255, 16]
            assert {item.provider_id for item in chunk} == {"lfdr"}
            assert {item.data_type for item in chunk} == {"uint8"}
            assert all(item.value_range == 256 for item in chunk)
            assert await store.reserve_remaining() == 0
            # партия исчерпана — честный None, без PRNG-подмены
            assert await store.reserve_draw(n=2, meta={"purpose": "p2"}) is None
            assert mrs.source_impl_for("lfdr") == "lfdr-quantum"
        finally:
            await db.close()

    @pytest.mark.asyncio
    async def test_lfdr_check_failure_is_honest(self):
        client, _ = make_client([(503, {}, '{"error": "Failed to read device"}')])
        result = await client.check()
        assert result["healthy"] is False
        assert result["blocker"] == "provider_unavailable"
        assert result["requires_key"] is False
        assert "values" not in result and "qrn" not in result


# ── ANU-клиент не изменён ───────────────────────────────────────────────────
class TestAnuUnchanged:
    @pytest.mark.asyncio
    async def test_anu_client_contract_still_intact(self):
        http_get, calls = make_http([
            (200, {}, '{"success": true, "type": "hex8", "length": 2, '
                      '"data": ["00ff", "abcd"]}')])
        client = mrs.AnuClient(http_get=http_get, min_interval=0.0,
                               clock=FakeClock())
        batch = await client.fetch(key="secret-key", length=2,
                                   data_type="hex8", size=2)
        assert batch.values == [255, 43981]
        assert batch.provider == mrs.PROVIDER_ID_ANU
        assert calls[0]["headers"] == {"x-api-key": "secret-key"}
        assert calls[0]["params"] == {"length": 2, "type": "hex8", "size": 2}
        assert calls[0]["url"] == mrs.ANU_ENDPOINT
