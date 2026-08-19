"""Tests for services/system_logs_fetcher.py (T-354-A #1-16, Sections 51.3/54.3).

Betterstack SQL API (ClickHouse HTTP, 54.3): httpx.MockTransport через параметр
transport конструктора (реальная сеть НИКОГДА); POST SQL-тела (шаблон-канон
R45-1 или sql_query-оверрайд), Basic auth, Content-type: plain/text,
output_format_pretty_row_numbers=0, парсинг JSONEachRow → «Timestamp - Level -
Message» (уровень из raw по keyword), потолки 200/20000; skip при пустых
host/user/password ИЛИ пустом SQL; 401/404/5xx/таймаут/ConnectError → journalctl.
journalctl: monkeypatch модульного атрибута asyncio.create_subprocess_shell
(fetcher импортирует asyncio модулем — прецедент 50.8); fake-процесс:
SimpleNamespace(returncode=…, communicate=AsyncMock(return_value=(stdout, stderr))).
"""
import asyncio
import base64
import json
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

SQL_HOST = "https://eu-fsn-3-connect.betterstackdata.com"


def _make_fetcher(transport, host=SQL_HOST, user="user", password="pass",
                  table="t123_x", query="", journalctl_cmd="journalctl -u admin_bot"):
    return CheckupLogsFetcher(
        sql_host=host, sql_user=user, sql_password=password, sql_table=table,
        sql_query=query, journalctl_cmd=journalctl_cmd, transport=transport,
    )


def _transport_with(handler):
    return httpx.MockTransport(handler)


def _json_handler(payload, status=200):
    def handler(request):
        return httpx.Response(status, json=payload, request=request)

    return _transport_with(handler)


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


def _jsoneachrow(rows):
    return "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n"


class TestFetcherSqlApi:
    @pytest.mark.asyncio
    async def test_canonical_jsoneachrow_200_format(self):
        """#1: 200 + канонический JSONEachRow {dt, raw} → «Timestamp - Level -
        Message»; used_fallback is False."""
        payload = _jsoneachrow([
            {"dt": "2026-08-20 10:00:00.000000", "raw": "ERROR disk exploded"},
        ])

        def handler(request):
            return httpx.Response(200, text=payload, request=request)

        fetcher = _make_fetcher(_transport_with(handler))
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is False
        assert text == "2026-08-20 10:00:00.000000 - ERROR - disk exploded"
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_basic_auth_and_post_and_param(self):
        """#2: Basic auth из user/password; метод POST; URL host +
        output_format_pretty_row_numbers=0 в params."""
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, text="", request=request)

        fetcher = _make_fetcher(_transport_with(handler))
        await fetcher.fetch()
        req = requests[0]
        assert req.method == "POST"
        assert str(req.url) == f"{SQL_HOST}?output_format_pretty_row_numbers=0"
        expected = "Basic " + base64.b64encode(b"user:pass").decode()
        assert req.headers["Authorization"] == expected
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_content_type_header_plain_text(self):
        """#3: хедер Content-type == "plain/text" (канон R45-1, НЕ text/plain)."""
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, text="", request=request)

        fetcher = _make_fetcher(_transport_with(handler))
        await fetcher.fetch()
        assert requests[0].headers["Content-type"] == "plain/text"
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_template_sql_body(self):
        """#4: тело SQL — шаблон-канон с table/limit, заканчивается
        FORMAT JSONEachRow."""
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, text="", request=request)

        fetcher = _make_fetcher(_transport_with(handler))
        await fetcher.fetch()
        body = requests[0].content.decode("utf-8")
        assert body == fetcher_mod._SQL_QUERY_TEMPLATE.format(table="t123_x", limit=200)
        assert body.endswith("FORMAT JSONEachRow")
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_sql_query_override_verbatim(self):
        """#5: sql_query задан → тело == query ВЕРБАТИМ (шаблон НЕ применяется)."""
        custom = "SELECT * FROM custom_logs LIMIT 7 FORMAT JSONEachRow"
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, text="", request=request)

        fetcher = _make_fetcher(_transport_with(handler), query=custom)
        await fetcher.fetch()
        assert requests[0].content.decode("utf-8") == custom
        await fetcher.close()

    @pytest.mark.parametrize(
        "raw,expected_level",
        [
            ("WARNING low memory", "WARNING"),
            ("Traceback (most recent call last)", "TRACEBACK"),
            ("ConnectionException raised", "EXCEPTION"),
            ("level: CRITICAL boom", "CRITICAL"),
            ("warn: disk is dying", "WARNING"),
        ],
    )
    def test_level_extracted_from_raw(self, raw, expected_level):
        """#6: маппинг уровня — первое keyword-вхождение в raw (warn → WARNING)."""
        level = CheckupLogsFetcher._extract_level(raw)
        assert level == expected_level

    @pytest.mark.asyncio
    async def test_local_level_filter(self):
        """#7: raw без keyword (info/debug) — строка НЕ попадает;
        5 релевантных из 7 → 5 строк."""
        rows = [
            {"dt": "2026-08-20 10:00:00", "raw": "ERROR a"},
            {"dt": "2026-08-20 10:00:01", "raw": "info noise"},
            {"dt": "2026-08-20 10:00:02", "raw": "debug noise"},
            {"dt": "2026-08-20 10:00:03", "raw": "WARNING b"},
            {"dt": "2026-08-20 10:00:04", "raw": "CRITICAL c"},
            {"dt": "2026-08-20 10:00:05", "raw": "fatal d"},
            {"dt": "2026-08-20 10:00:06", "raw": "exception e"},
        ]

        def handler(request):
            return httpx.Response(200, text=_jsoneachrow(rows), request=request)

        fetcher = _make_fetcher(_transport_with(handler))
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is False
        assert len(text.splitlines()) == 5
        assert "info noise" not in text and "debug noise" not in text
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_broken_jsoneachrow_line_skipped_with_warning(self, caplog):
        """#8: кривая JSONEachRow-строка → пропуск + WARNING; валидные соседи
        сохранены."""
        import logging

        payload = (
            '{"dt": "2026-08-20 10:00:00", "raw": "ERROR one"}\n'
            'this is not json\n'
            '{"dt": "2026-08-20 10:00:01", "raw": "WARNING two"}\n'
        )

        def handler(request):
            return httpx.Response(200, text=payload, request=request)

        fetcher = _make_fetcher(_transport_with(handler))
        with caplog.at_level(logging.WARNING):
            text, used_fallback = await fetcher.fetch()
        assert used_fallback is False
        assert text.splitlines() == [
            "2026-08-20 10:00:00 - ERROR - one",
            "2026-08-20 10:00:01 - WARNING - two",
        ]
        assert any("broken JSONEachRow" in r.message for r in caplog.records)
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_non_json_body_is_valid_empty_not_fallback(self, monkeypatch, caplog):
        """#9: 200 + не-JSON-тело → все строки битые → («», False) — ВАЛИДНЫЙ
        «логов нет», НЕ фолбек (journalctl НЕ вызывается)."""
        import logging

        def handler(request):
            return httpx.Response(200, text="<html>error page</html>", request=request)

        fetcher = _make_fetcher(_transport_with(handler))
        with caplog.at_level(logging.WARNING):
            text, used_fallback = await fetcher.fetch()
        assert (text, used_fallback) == ("", False)
        assert any("broken JSONEachRow" in r.message for r in caplog.records)
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_numeric_dt_converted_via_fromtimestamp(self):
        """#10: числовой dt → fromtimestamp UTC; вне диапазона → как есть."""
        ts = 1755684000
        payload = _jsoneachrow([
            {"dt": ts, "raw": "ERROR numeric"},
            {"dt": "99999999999", "raw": "ERROR out of range"},
        ])

        def handler(request):
            return httpx.Response(200, text=payload, request=request)

        fetcher = _make_fetcher(_transport_with(handler))
        text, _ = await fetcher.fetch()
        lines = text.splitlines()
        assert lines[0] == f"{_unix_expected(ts)} - ERROR - numeric"
        assert lines[1].startswith("99999999999 - ERROR - ")
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_cap_200_events(self):
        """#11: 250 релевантных → ровно 200 строк."""
        rows = [
            {"dt": f"2026-08-20 10:00:{i % 60:02d}", "raw": f"ERROR event {i}"}
            for i in range(250)
        ]

        def handler(request):
            return httpx.Response(200, text=_jsoneachrow(rows), request=request)

        fetcher = _make_fetcher(_transport_with(handler))
        text, _ = await fetcher.fetch()
        assert len(text.splitlines()) == 200
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_symbol_cap_20000(self):
        """#11: >20000 символов → обрезка до 20000."""
        rows = [
            {"dt": "2026-08-20 10:00:00", "raw": f"ERROR {'x' * 300} {i}"}
            for i in range(80)
        ]

        def handler(request):
            return httpx.Response(200, text=_jsoneachrow(rows), request=request)

        fetcher = _make_fetcher(_transport_with(handler))
        text, _ = await fetcher.fetch()
        assert len(text) == fetcher_mod._MAX_LOG_SYMBOLS
        await fetcher.close()

    @pytest.mark.parametrize("user,password", [("", "pass"), ("user", ""), ("", "")])
    @pytest.mark.asyncio
    async def test_empty_credentials_skip_sql(self, monkeypatch, user, password):
        """#12: пустые user/password → SQL API НЕ вызван (0 запросов),
        сразу journalctl, (text, True)."""
        shell = AsyncMock(return_value=_fake_proc(stdout=b"ERROR local\n"))
        monkeypatch.setattr(fetcher_mod.asyncio, "create_subprocess_shell", shell)
        requests = []

        fetcher = CheckupLogsFetcher(
            sql_host=SQL_HOST, sql_user=user, sql_password=password,
            sql_table="t123_x", sql_query="",
            transport=_transport_with(lambda r: requests.append(r) or None),
        )
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is True
        assert requests == []
        assert text == "ERROR local"
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_empty_table_and_query_skip_sql(self, monkeypatch):
        """#13: пустой table И пустой query → skip → journalctl (0 запросов)."""
        shell = AsyncMock(return_value=_fake_proc(stdout=b"ERROR local\n"))
        monkeypatch.setattr(fetcher_mod.asyncio, "create_subprocess_shell", shell)
        requests = []

        fetcher = CheckupLogsFetcher(
            sql_host=SQL_HOST, sql_user="user", sql_password="pass",
            sql_table="", sql_query="",
            transport=_transport_with(lambda r: requests.append(r) or None),
        )
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is True
        assert requests == []
        assert text == "ERROR local"
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_empty_query_with_table_uses_template(self):
        """#14: пустой query + table задан → шаблон с table применяется
        (запрос ушёл)."""
        requests = []

        def handler(request):
            requests.append(request)
            return httpx.Response(200, text="", request=request)

        fetcher = CheckupLogsFetcher(
            sql_host=SQL_HOST, sql_user="user", sql_password="pass",
            sql_table="t9_z", sql_query="", transport=_transport_with(handler),
        )
        _, used_fallback = await fetcher.fetch()
        assert used_fallback is False
        assert len(requests) == 1
        assert requests[0].content.decode("utf-8") == fetcher_mod._SQL_QUERY_TEMPLATE.format(
            table="t9_z", limit=200
        )
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_empty_host_skip_sql(self, monkeypatch):
        shell = AsyncMock(return_value=_fake_proc(stdout=b"ERROR local\n"))
        monkeypatch.setattr(fetcher_mod.asyncio, "create_subprocess_shell", shell)
        fetcher = CheckupLogsFetcher(
            sql_host="", sql_user="user", sql_password="pass", sql_table="t",
        )
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is True
        assert text == "ERROR local"
        await fetcher.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [401, 404, 500])
    async def test_http_errors_fall_back_to_journalctl(self, monkeypatch, status):
        """#15: 401/404/500 (raise_for_status) → journalctl, (text, True)."""
        monkeypatch.setattr(
            fetcher_mod.asyncio,
            "create_subprocess_shell",
            AsyncMock(return_value=_fake_proc(stdout=b"ERROR local\nINFO noise\n")),
        )
        fetcher = _make_fetcher(_json_handler({"error": "boom"}, status=status))
        text, used_fallback = await fetcher.fetch()
        assert used_fallback is True
        assert text == "ERROR local"
        await fetcher.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "exc",
        [httpx.ConnectTimeout("t", request=None), httpx.ConnectError("conn")],
    )
    async def test_timeout_and_connect_error_fall_back(self, monkeypatch, exc):
        """#15: таймаут/ConnectError (RequestError) → journalctl."""
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
    async def test_close_releases_client(self):
        """#16: close() освобождает клиента."""
        fetcher = _make_fetcher(_transport_with(
            lambda r: httpx.Response(200, text="", request=r)
        ))
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
        fetcher = CheckupLogsFetcher(sql_user="")
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
        fetcher = CheckupLogsFetcher(sql_user="")
        text, _ = await fetcher.fetch()
        assert len(text.splitlines()) == fetcher_mod._JOURNALCTL_MAX_LINES
        assert text.endswith("ERROR line 349")
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_rc0_empty_stdout_is_valid_not_dead(self, monkeypatch):
        """#21: rc=0 + пустой stdout → («», True) — ВАЛИДНО, НЕ dead."""
        _patch_journalctl(monkeypatch, _fake_proc(stdout=b"", stderr=b""))
        fetcher = CheckupLogsFetcher(sql_user="")
        text, used_fallback = await fetcher.fetch()
        assert (text, used_fallback) == ("", True)
        await fetcher.close()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("rc,stderr", [(127, b"/bin/sh: journalctl: not found"), (1, b"Hint: You are currently not seeing messages")])
    async def test_nonzero_rc_raises_unavailable(self, monkeypatch, rc, stderr):
        """#22: rc=127/rc=1 + stderr hint → CheckupLogsUnavailableException."""
        _patch_journalctl(monkeypatch, _fake_proc(returncode=rc, stderr=stderr))
        fetcher = CheckupLogsFetcher(sql_user="")
        with pytest.raises(CheckupLogsUnavailableException):
            await fetcher.fetch()
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_spawn_oserror_raises_unavailable(self, monkeypatch):
        """#23: create_subprocess_shell бросает OSError → raise."""
        async def fake_shell(cmd, stdout=None, stderr=None):
            raise OSError("no such binary")

        monkeypatch.setattr(fetcher_mod.asyncio, "create_subprocess_shell", fake_shell)
        fetcher = CheckupLogsFetcher(sql_user="")
        with pytest.raises(CheckupLogsUnavailableException):
            await fetcher.fetch()
        await fetcher.close()

    @pytest.mark.asyncio
    async def test_communicate_timeout_raises_unavailable(self, monkeypatch):
        """#23: communicate таймаутит → raise."""
        proc = _fake_proc(comm_error=asyncio.TimeoutError)
        _patch_journalctl(monkeypatch, proc)
        fetcher = CheckupLogsFetcher(sql_user="")
        with pytest.raises(CheckupLogsUnavailableException):
            await fetcher.fetch()
        await fetcher.close()
