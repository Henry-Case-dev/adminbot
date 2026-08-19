"""Tests for services/system_logs_fetcher.py (T-330-A #11-23, Section 51.3).

Betterstack: httpx.MockTransport через параметр transport конструктора
(реальная сеть НИКОГДА). journalctl: monkeypatch модульного атрибута
asyncio.create_subprocess_shell (fetcher импортирует asyncio модулем —
прецедент 50.8); fake-процесс: SimpleNamespace(returncode=…,
communicate=AsyncMock(return_value=(stdout, stderr))).
"""
import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from services import system_logs_fetcher as fetcher_mod
from services.system_logs_fetcher import (
    CheckupLogsFetcher,
    CheckupLogsUnavailableException,
)

BASE_URL = "https://logs.betterstack.com/api/v2/events"


def _make_fetcher(transport, token="tok-123"):
    return CheckupLogsFetcher(token=token, transport=transport)


def _transport_with(handler):
    return httpx.MockTransport(handler)


def _json_handler(payload, status=200):
    def handler(request):
        return httpx.Response(status, json=payload, request=request)

    return _transport_with(handler)


def _attr_event(message, level, dt):
    return {"id": "e", "attributes": {"message": message, "level": level, "dt": dt}}


def _patch_journalctl(monkeypatch, proc):
    async def fake_shell(cmd, stdout=None, stderr=None):
        return proc

    monkeypatch.setattr(fetcher_mod.asyncio, "create_subprocess_shell", fake_shell)
    return proc


def _fake_proc(stdout=b"", stderr=b"", returncode=0, comm_error=None):
    proc = SimpleNamespace(returncode=returncode)
    if comm_error is not None:
        proc.communicate = AsyncMock(side_effect=comm_error)
    else:
        proc.communicate = AsyncMock(return_value=(stdout, stderr))
    return proc


def _unix_expected(ts: int) -> str:
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


class TestFetcherBetterstack:
    @pytest.mark.asyncio
    async def test_jsonapi_200_format_and_params(self, monkeypatch):
        """#11: 200 + JSON:API (data[].attributes{message,level,dt});
        fetch → (text, False); from/to ISO8601 на 1-м запросе."""
        payload = {
            "data": [
                _attr_event("disk exploded", "error", "2026-08-20T10:00:00+00:00"),
                _attr_event("just an info", "info", "2026-08-20T10:01:00+00:00"),
            ],
            "pagination": {"first": None, "next": None},
        }
        fetcher = _make_fetcher(_json_handler(payload))
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is False
        assert text == "2026-08-20T10:00:00+00:00 - ERROR - disk exploded"
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_from_to_params_on_first_request(self):
        payload = {
            "data": [_attr_event("boom", "error", "2026-08-20T10:00:00+00:00")],
            "pagination": {"first": None, "next": None},
        }
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, json=payload, request=request)

        fetcher = _make_fetcher(_transport_with(handler))
        await fetcher.fetch()
        assert requests[0].url.path == "/api/v2/events"
        assert "from" in requests[0].url.params and "to" in requests[0].url.params
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_flat_schema_unix_ts(self):
        """#12: плоская схема (data[]{message,level,_dt}) → unix → формат-ts."""
        ts = 1755684000
        payload = {
            "data": [
                {"message": "kernel panic", "level": "CRITICAL", "_dt": ts},
            ],
            "pagination": {"first": None, "next": None},
        }
        fetcher = _make_fetcher(_json_handler(payload))
        text, _ = await fetcher.fetch()
        assert text == f"{_unix_expected(ts)} - CRITICAL - kernel panic"
        await fetcher.close()

    def test_extract_lines_tolerant_variants(self):
        """Толерантный контракт: attributes/плоские поля, алиасы message/level/ts,
        events-fallback при data-не-списке, не-dict элементы пропускаются,
        нет ts → «-»."""
        payload = {
            "data": [
                {"attributes": {"message": "a", "level": "error", "dt": "T1"}},
                {"msg": "b", "severity": "warning", "timestamp": "T2"},
                {"json": "c", "log_level": "alert", "_dt": 1755684000},
                {"message": "d", "level": "fatal"},
                "not-a-dict",
                {"message": "e", "level": "info"},       # нерелевантный уровень
            ],
            "pagination": {"next": None},
        }
        lines = CheckupLogsFetcher._extract_lines(payload)
        assert lines == [
            "T1 - ERROR - a",
            "T2 - WARNING - b",
            f"{_unix_expected(1755684000)} - ALERT - c",
            "- - FATAL - d",
        ]

    def test_extract_lines_events_fallback_when_data_not_list(self):
        payload = {
            "data": {"broken": "object"},
            "events": [{"message": "x", "level": "error", "dt": "T1"}],
        }
        lines = CheckupLogsFetcher._extract_lines(payload)
        assert lines == ["T1 - ERROR - x"]

    def test_extract_lines_numeric_ts_out_of_range_kept_raw(self):
        """Числовой ts вне диапазона fromtimestamp → except → ts как есть
        (защитная ветка 51.3)."""
        payload = {
            "data": [{"message": "x", "level": "error", "_dt": "99999999999"}],
            "pagination": {"next": None},
        }
        lines = CheckupLogsFetcher._extract_lines(payload)
        assert lines == ["99999999999 - ERROR - x"]

    def test_extract_lines_message_in_json_field_and_level_filter(self):
        """#13: фильтр уровней — ЛОКАЛЬНО по level+message (имена ключей
        level/severity, ключевые слова в message: Exception/Traceback).
        Формат строки — «ts - LEVEL - message» (level — как в событии)."""
        payload = {
            "data": [
                {"message": "all good", "level": "info"},                          # мимо
                {"message": "doing fine", "severity": "debug"},                    # мимо
                {"message": "Traceback (most recent call last)", "level": "info"}, # в message
                {"message": "ConnectionException raised", "level": "info"},        # exception
                {"message": "boom", "level": "CRITICAL"},
                {"message": "fyi", "level": "warning"},
                {"json": "{\"msg\": \"alert!\"}", "level": "alert"},
            ],
            "pagination": {"next": None},
        }
        lines = CheckupLogsFetcher._extract_lines(payload)
        assert len(lines) == 5
        assert lines[0].endswith("- INFO - Traceback (most recent call last)")
        assert lines[1].endswith("- INFO - ConnectionException raised")
        assert lines[2].endswith("- CRITICAL - boom")
        assert lines[3].endswith("- WARNING - fyi")
        assert lines[4].endswith('- ALERT - {"msg": "alert!"}')

    @pytest.mark.asyncio
    async def test_cap_200_events(self):
        """#14: >200 релевантных событий → ровно 200 строк."""
        payload = {
            "data": [
                {"message": f"err {i}", "level": "error", "dt": f"T{i}"}
                for i in range(250)
            ],
            "pagination": {"first": None, "next": None},
        }
        fetcher = _make_fetcher(_json_handler(payload))
        text, _ = await fetcher.fetch()
        assert len(text.splitlines()) == 200
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_pagination_follows_next_two_pages(self):
        """#15: pagination.next → 2-й GET без params, события объединены."""
        page1 = {
            "data": [{"message": "one", "level": "error", "dt": "T1"}],
            "pagination": {"next": f"{BASE_URL}?page=2"},
        }
        page2 = {
            "data": [{"message": "two", "level": "warning", "dt": "T2"}],
            "pagination": {"next": None},
        }
        requests = []

        def handler(request):
            requests.append(request)
            payload = page1 if "page=2" not in str(request.url) else page2
            return httpx.Response(200, json=payload, request=request)

        fetcher = _make_fetcher(_transport_with(handler))
        text, _ = await fetcher.fetch()
        assert len(requests) == 2
        assert "from" in requests[0].url.params and "to" in requests[0].url.params
        assert "page" not in requests[0].url.params
        assert "from" not in requests[1].url.params   # params только на 1-й странице
        assert text.splitlines() == ["T1 - ERROR - one", "T2 - WARNING - two"]
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_pagination_capped_at_max_pages(self, monkeypatch):
        """next всегда есть → стоп на _MAX_PAGES, ровно 5 GET."""
        requests = []

        def handler(request):
            requests.append(request)
            payload = {
                "data": [{"message": f"e{len(requests)}", "level": "error", "dt": "T"}],
                "pagination": {"next": f"{BASE_URL}?page={len(requests) + 1}"},
            }
            return httpx.Response(200, json=payload, request=request)

        fetcher = _make_fetcher(_transport_with(handler))
        text, _ = await fetcher.fetch()
        assert len(requests) == fetcher_mod._MAX_PAGES == 5
        assert len(text.splitlines()) == 5
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_401_falls_back_to_journalctl(self, monkeypatch):
        """#16: 401 (raise_for_status) → journalctl → (text, True)."""
        monkeypatch.setattr(
            fetcher_mod.asyncio,
            "create_subprocess_shell",
            AsyncMock(return_value=_fake_proc(stdout=b"ERROR local\nINFO noise\n")),
        )
        fetcher = _make_fetcher(_json_handler({"error": "unauthorized"}, status=401))
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is True
        assert text == "ERROR local"
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_500_falls_back(self, monkeypatch):
        monkeypatch.setattr(
            fetcher_mod.asyncio,
            "create_subprocess_shell",
            AsyncMock(return_value=_fake_proc(stdout=b"ERROR local\n")),
        )
        fetcher = _make_fetcher(_json_handler({}, status=500))
        _, used_fallback = await fetcher.fetch()
        assert used_fallback is True
        await fetcher.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exc",
        [httpx.ConnectTimeout("t", request=None), httpx.ConnectError("conn")],
    )
    async def test_timeout_and_connect_error_fall_back(self, monkeypatch, exc):
        """#17: таймаут/ConnectError (RequestError) → journalctl."""
        monkeypatch.setattr(
            fetcher_mod.asyncio,
            "create_subprocess_shell",
            AsyncMock(return_value=_fake_proc(stdout=b"ERROR local\n")),
        )

        def handler(request):
            if isinstance(exc, httpx.ConnectTimeout):
                raise httpx.ConnectTimeout("t", request=request)
            raise httpx.ConnectError("conn", request=request)

        fetcher = _make_fetcher(_transport_with(handler))
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is True
        assert text == "ERROR local"
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_broken_json_falls_back(self, monkeypatch):
        """#18: 200 + битый JSON → ValueError → фолбек."""
        monkeypatch.setattr(
            fetcher_mod.asyncio,
            "create_subprocess_shell",
            AsyncMock(return_value=_fake_proc(stdout=b"ERROR local\n")),
        )

        def handler(request):
            return httpx.Response(200, text="<html>not json</html>", request=request)

        fetcher = _make_fetcher(_transport_with(handler))
        _, used_fallback = await fetcher.fetch()
        assert used_fallback is True
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_empty_token_skips_betterstack(self, monkeypatch):
        """#19: пустой токен → betterstack НЕ вызван, сразу journalctl, (text, True)."""
        shell = AsyncMock(return_value=_fake_proc(stdout=b"ERROR local\n"))
        monkeypatch.setattr(fetcher_mod.asyncio, "create_subprocess_shell", shell)
        requests = []

        fetcher = CheckupLogsFetcher(
            token="", transport=_transport_with(lambda r: requests.append(r) or None)
        )
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is True
        assert requests == []
        assert text == "ERROR local"
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_close_releases_client(self):
        fetcher = _make_fetcher(_json_handler({"data": [], "pagination": {"next": None}}))
        await fetcher.fetch()
        assert fetcher._client is not None
        await fetcher.close()
        assert fetcher._client is None


class TestFetcherJournalctl:
    @pytest.mark.asyncio
    async def test_rc0_filters_error_warning_traceback(self, monkeypatch):
        """#20: rc=0 + вывод → только ERROR/WARNING/Traceback-строки."""
        stdout = b"\n".join(
            [
                b"Aug 20 10:00:00 host bot[1]: INFO all fine",
                b"Aug 20 10:00:01 host bot[1]: ERROR disk exploded",
                b"Aug 20 10:00:02 host bot[1]: WARNING low memory",
                b"Aug 20 10:00:03 host bot[1]: Traceback (most recent call last):",
                b"Aug 20 10:00:04 host bot[1]: INFO still fine",
            ]
        )
        proc = _fake_proc(stdout=stdout)
        _patch_journalctl(monkeypatch, proc)
        fetcher = CheckupLogsFetcher(token="")
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is True
        lines = text.splitlines()
        assert len(lines) == 3
        assert all(
            any(m in line.lower() for m in ("error", "warning", "traceback"))
            for line in lines
        )
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_rc0_keeps_last_300_lines(self, monkeypatch):
        stdout = b"\n".join(f"ERROR line {i}".encode() for i in range(350))
        _patch_journalctl(monkeypatch, _fake_proc(stdout=stdout))
        fetcher = CheckupLogsFetcher(token="")
        text, _ = await fetcher.fetch()
        assert len(text.splitlines()) == fetcher_mod._JOURNALCTL_MAX_LINES
        assert text.endswith("ERROR line 349")
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_rc0_empty_stdout_is_valid_not_dead(self, monkeypatch):
        """#21: rc=0 + пустой stdout → («», True) — ВАЛИДНО, НЕ dead."""
        _patch_journalctl(monkeypatch, _fake_proc(stdout=b"", stderr=b""))
        fetcher = CheckupLogsFetcher(token="")
        text, used_fallback = await fetcher.fetch()
        assert (text, used_fallback) == ("", True)
        await fetcher.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("rc,stderr", [(127, b"/bin/sh: journalctl: not found"), (1, b"Hint: You are currently not seeing messages")])
    async def test_nonzero_rc_raises_unavailable(self, monkeypatch, rc, stderr):
        """#22: rc=127/rc=1 + stderr hint → CheckupLogsUnavailableException."""
        _patch_journalctl(monkeypatch, _fake_proc(returncode=rc, stderr=stderr))
        fetcher = CheckupLogsFetcher(token="")
        with pytest.raises(CheckupLogsUnavailableException):
            await fetcher.fetch()
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_spawn_oserror_raises_unavailable(self, monkeypatch):
        """#23: create_subprocess_shell бросает OSError → raise."""
        async def fake_shell(cmd, stdout=None, stderr=None):
            raise OSError("no such binary")

        monkeypatch.setattr(fetcher_mod.asyncio, "create_subprocess_shell", fake_shell)
        fetcher = CheckupLogsFetcher(token="")
        with pytest.raises(CheckupLogsUnavailableException):
            await fetcher.fetch()
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_communicate_timeout_raises_unavailable(self, monkeypatch):
        """#23: communicate таймаутит → raise."""
        proc = _fake_proc(comm_error=asyncio.TimeoutError)
        _patch_journalctl(monkeypatch, proc)
        fetcher = CheckupLogsFetcher(token="")
        with pytest.raises(CheckupLogsUnavailableException):
            await fetcher.fetch()
        await fetcher.close()
