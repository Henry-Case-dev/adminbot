"""S7 round1026 (ADR-1026-9 D1–D8) — сквозной `run_id` и логирование Саммари.

Покрытие SC-01…SC-15 (задачи T-3383…T-3401):
  * SC-01 — один `run_id` (= `correlation_id`) на прогон; все этапные строки
    несут его; второй идентификатор не создаётся;
  * SC-02 — `SUMMARY_START`/`SUMMARY_COMPLETE`/`SUMMARY_FAILED` различимы
    (ok/empty/degraded/failed);
  * SC-03…SC-06 — `FILTER_*`/`L1_*`/`L2_*`/`FORMAT_*`/`COVER_*` с полями §109;
  * SC-07 — fail-closed: `*_ERROR` несут run_id/host/HTTP-статус/тип/причину/
    попытки; голой «Ошибка Саммари» нет;
  * SC-08/SC-12 — R17 (без ключей/промптов/сырых текстов); Δ каталога=0;
  * SC-13 — OFF-путь по артефактам/поведению неизменен, 2-вызовность;
  * SC-14 — dry-run S9: `TEST_*` + этапные, без `SUMMARY_*`/`PUBLISH_*`;
  * SC-15 — `PUBLISH_RICH_*`/`PUBLISH_TEXT_*` — S6: реализованы в живом
    публикационном контуре, события только при реальной публикации;
    dry-run S9 — без `PUBLISH_*` (перепрофилировано, не удалено).
"""
from __future__ import annotations

import dataclasses
import json
import logging
import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import APP_VERSION, Settings
from services import param_catalog as pc
from services import summary_generator as sg
from services import usage_events
from services.llm_client import (
    LLMError,
    LLMRateLimitError,
    LLMServerError,
    LLMTimeoutError,
)
from services.summary_generator import SummaryGenerator
from services.summary_l1_contract import L1Result
from services.summary_l1_clusterizer import run_l1
from services.summary_l2_writer import run_l2
from services.summary_run_log import (
    STATUS_DEGRADED,
    STATUS_EMPTY,
    STATUS_FAILED,
    RunContext,
    attempts_of,
    finish_run,
    http_status_of,
    provider_host,
)
from services.summary_test_run import STATUS_ERROR, STATUS_OK, run_summary_test
from services.summary_xml import XmlGroundingBuilder
from services import summary_test_run as str_mod

from tests.test_summary_generator import FakeMemory, _row
from tests.test_summary_test_run import (
    CHAT_ID as DRY_CHAT,
    L1_JSON,
    L2_JSON,
    _fake_llm,
    _real_generator,
    _rows as _dry_rows,
)

ROOT = Path(__file__).resolve().parents[1]

CHAT = -1001
_RID = "RID-S7-0001"
_FLAG = "flags.summary_filter_enabled"
_S2_FLAG = "flags.summary_filter_reply_context_enabled"
_HYBRID_FLAG = "flags.summary_hybrid_l2_enabled"
_FAKE_KEY = "SUPER-SECRET-KEY-LEAK-1"

_DIGEST = "# Событие\n- Вася спорил с Петей про футбол"


# ── helpers ────────────────────────────────────────────────────────────────

def _rows():
    return [
        _row(id=1, tg_message_id=101, user_id=10, text="@vasya привет",
             timestamp=1000),
        _row(id=2, tg_message_id=102, user_id=11, text="мусор",
             timestamp=1001),
    ]


def _patch_chat_limit(monkeypatch, overrides=None):
    overrides = dict(overrides or {})

    async def _fake(chat_id, key, default=None):
        if (chat_id, key) in overrides:
            return overrides[(chat_id, key)]
        if key == _HYBRID_FLAG:
            # S10 (ADR-1026-12 D2): Hybrid default ON — legacy/ON-тесты этого
            # модуля включают режим ЯВНО (`_HYBRID_FLAG: True`), остальные
            # (OFF-lifecycle) фиксируют явный аварийный OFF.
            return False
        return default

    monkeypatch.setattr(sg, "_chat_limit", _fake)


def _patch_delivery(monkeypatch):
    rec = {"plain": [], "rich": []}

    async def _plain(self, chat_id, text, *a, **kw):
        rec["plain"].append(text)

    async def _rich(self, chat_id, text, *a, **kw):
        rec["rich"].append(text)

    monkeypatch.setattr(SummaryGenerator, "_deliver_plain", _plain)
    monkeypatch.setattr(SummaryGenerator, "_deliver_rich", _rich)
    return rec


def _gen(memory, llm, **kwargs):
    return SummaryGenerator(memory, XmlGroundingBuilder(), llm,
                            AsyncMock(), **kwargs)


def _lines(caplog, name):
    return [r.getMessage() for r in caplog.records
            if r.getMessage().startswith(name + " |")]


def _event_lines(caplog, name):
    """Существующий формат S1/S2: ``summary filter: event=FILTER_START | …``."""
    return [r.getMessage() for r in caplog.records
            if ("event=" + name + " ") in r.getMessage()]


def _rid(line):
    match = re.search(r"run_id=(\S+)", line)
    return match.group(1) if match else None


def _fixed_rid(monkeypatch):
    monkeypatch.setattr(usage_events, "new_correlation_id", lambda: _RID)


class _HttpErr(Exception):
    """Исключение с §109-атрибутами (status_code/attempts) для *_ERROR-веток."""

    def __init__(self, message, *, status_code=None, attempts=None):
        super().__init__(message)
        self.status_code = status_code
        self.attempts = attempts


class TwoCallLLM:
    def __init__(self):
        self.calls = 0
        self.correlation_ids = []

    async def generate(self, messages, **kwargs):
        self.calls += 1
        self.correlation_ids.append(kwargs.get("correlation_id"))
        return _DIGEST if self.calls == 1 else "связный дерзкий рассказ"


def _hybrid_env(monkeypatch):
    """ON-ветка `_run` на моках S3/S4; L2 — реальный `run_l2` (1 вызов)."""
    payload = {
        "schema_version": 1,
        "threads": [{
            "thread_id": "thread_001", "topic": "Погода",
            "message_ids": [101],
            "facts": [{"text": "шёл дождь",
                       "evidence_message_ids": [101]}],
        }],
        "unassigned_message_ids": [],
    }
    l1_result = L1Result(
        status="ok", payload=payload, invalid_reason=None, threads_count=1,
        facts_count=1, auto_unassigned_count=0, skipped_ids=(),
        skipped_tg_ids=(), response_mode="serious", cover_prompt="",
        duration_ms=1.0)
    package = {
        "schema_version": 1, "status": "ok",
        "threads": [{
            "thread_id": "thread_001", "name": "Погода",
            "description": "шёл дождь",
            "chronology": [{"message_id": 101, "timestamp": 1}],
            "facts": [{"text": "шёл дождь",
                       "evidence_message_ids": [101]}],
            "evidence_ids": [101],
            "fragments": [{"message_id": 101, "timestamp": 1,
                           "text": "шёл дождь"}],
        }],
        "unassigned_message_ids": [], "service": {
            "response_mode": "serious", "cover_prompt": ""},
        "budget": {"kind": "tokens", "limit": 30000, "estimated": 1,
                   "fits": True},
    }
    from services.summary_fact_package import FactPackageResult
    package_result = FactPackageResult(
        status="ok", package=package, reason="ok", metrics={}, budget={})

    async def fake_run_l1(**kwargs):
        return l1_result

    def fake_build_package(*a, **k):
        return package_result

    monkeypatch.setattr("services.summary_l1_clusterizer.run_l1",
                        fake_run_l1)
    monkeypatch.setattr("services.summary_fact_package.build_fact_package",
                        fake_build_package)
    monkeypatch.setattr(
        "services.summary_context_restore.build_l1_payload",
        lambda rows, chat_id: [{"message_id": 101, "timestamp": 1,
                                "text": "шёл дождь"}])


# ── Unit: summary_run_log (D1/D2/D6) ───────────────────────────────────────

class TestRunLogHelpers:
    def test_provider_host_strips_scheme_path_key(self):
        assert provider_host(
            f"https://api.example.com/v1?key={_FAKE_KEY}") == "api.example.com"
        assert provider_host("") == ""
        assert provider_host(None) == ""

    def test_http_status_of(self):
        assert http_status_of(_HttpErr("x", status_code=429)) == 429
        assert http_status_of(LLMError("HTTP 403 forbidden")) == 403
        assert http_status_of(LLMError("server error 502 after 3 attempts")) == 502
        assert http_status_of(LLMError("auth failed (401)")) == 401
        assert http_status_of(LLMError("rate limited (429)")) == 429
        assert http_status_of(LLMError("просто текст")) is None
        # B-R1026S7-2: реальные тексты llm_client парсятся (консистентность).
        assert http_status_of(LLMRateLimitError(
            "LLM rate limited (429) after 3 attempts: https://api.test/v1")) == 429
        assert http_status_of(LLMServerError(
            "LLM server error 502 after 3 attempts: https://api.test/v1")) == 502
        assert http_status_of(LLMTimeoutError(
            "LLM request timed out after 3 attempts: https://api.test/v1")) is None

    def test_attempts_of(self):
        assert attempts_of(_HttpErr("x", attempts=3)) == 3
        assert attempts_of(LLMError("x")) is None

    def test_attempts_of_real_llm_texts(self):
        """B-R1026S7-2: число попыток из реального текста (атрибута нет)."""
        assert attempts_of(LLMRateLimitError(
            "LLM rate limited (429) after 3 attempts: https://api.test/v1")) == 3
        assert attempts_of(LLMServerError(
            "LLM server error 502 after 3 attempts: https://api.test/v1")) == 3
        assert attempts_of(LLMTimeoutError(
            "LLM request timed out after 2 attempts: https://api.test/v1")) == 2
        assert attempts_of(LLMError("просто текст")) is None
        # Fallback на атрибут, если в тексте числа попыток нет.
        assert attempts_of(_HttpErr("x", attempts=4)) == 4
        # Текст приоритетнее атрибута (реальный прод-путь — текст).
        assert attempts_of(_HttpErr(
            "server error 500 after 5 attempts", attempts=4)) == 5

    def test_fail_from_exc_r17_fields(self):
        ctx = RunContext(run_id=_RID, chat_id=CHAT)
        exc = _HttpErr(f"boom {_FAKE_KEY}", status_code=500, attempts=2)
        ctx.fail_from_exc(stage="l1", exc=exc)
        assert ctx.status == STATUS_FAILED
        assert ctx.stage == "l1"
        assert ctx.error_type == "_HttpErr"
        assert ctx.http_status == 500
        assert ctx.attempts == 2
        assert _FAKE_KEY not in (ctx.reason or "")

    def test_finish_run_picks_failed_or_complete(self, caplog):
        with caplog.at_level(logging.INFO):
            ok = RunContext(run_id=_RID, chat_id=CHAT)
            ok.status = STATUS_EMPTY
            finish_run(ok)
            bad = RunContext(run_id=_RID, chat_id=CHAT)
            bad.fail(stage="l2", reason="llm_error", error_type="LLMError")
            finish_run(bad)
        assert _lines(caplog, "SUMMARY_COMPLETE")
        assert "status=empty" in _lines(caplog, "SUMMARY_COMPLETE")[0]
        failed = _lines(caplog, "SUMMARY_FAILED")
        assert failed and "stage=l2" in failed[0] and _RID in failed[0]

    def test_lifecycle_fields(self, caplog):
        ctx = RunContext(run_id=_RID, chat_id=CHAT, mode="hybrid_l2",
                         manual=True, has_trigger=True, source_count=5,
                         saved_count=3, restored_count=2, threads=1,
                         paragraphs=4, cover_status="ok")
        with caplog.at_level(logging.INFO):
            finish_run(ctx)
        line = _lines(caplog, "SUMMARY_COMPLETE")[0]
        for needle in ("mode=hybrid_l2", "status=ok", "source_count=5",
                       "saved_count=3", "restored_count=2", "threads=1",
                       "paragraphs=4", "cover_status=ok", "duration_ms="):
            assert needle in line, needle


# ── SC-01/SC-02/SC-03: живой OFF-путь `_run` ───────────────────────────────

class TestRunLifecycleOff:
    @pytest.mark.asyncio
    async def test_single_run_id_all_events(self, monkeypatch, caplog):
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {(CHAT, _FLAG): True,
                                        (CHAT, _S2_FLAG): False})
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", True)
        monkeypatch.setattr(Settings, "SUMMARY_COVER_ARTICLE_ENABLED", False)
        rec = _patch_delivery(monkeypatch)
        gen = _gen(FakeMemory(rows=_rows()), TwoCallLLM())

        with caplog.at_level(logging.INFO):
            await gen._run(CHAT, False)

        assert gen.llm.calls == 2                      # 2-вызовность сохранена
        # SC-11: тот же id уходит в учёт LLM (`llm_usage_events` по run_id).
        assert gen.llm.correlation_ids == [_RID, _RID]
        assert rec["plain"] and "дерзкий рассказ" in rec["plain"][0]
        text = caplog.text
        # S6 (ADR-1026-11 D6): доставка замокана → реальной публикации нет →
        # PUBLISH_* не эмитятся (события только при реальной публикации).
        assert "PUBLISH_" not in text
        start = _lines(caplog, "SUMMARY_START")
        assert start and "mode=off" in start[0]
        assert "source_count=-" in start[0]            # окно ещё не прочитано
        complete = _lines(caplog, "SUMMARY_COMPLETE")
        assert complete and "status=ok" in complete[0]
        assert "source_count=2" in complete[0]
        assert "saved_count=1" in complete[0]          # §109: из метрик прогона
        assert "restored_count=0" in complete[0]
        assert (_event_lines(caplog, "FILTER_START")
                and _event_lines(caplog, "FILTER_COMPLETE"))
        # SC-01: каждая этапная строка несёт ОДИН и тот же run_id.
        stage_lines = (_lines(caplog, "SUMMARY_START")
                       + _lines(caplog, "SUMMARY_COMPLETE")
                       + _event_lines(caplog, "FILTER_START")
                       + _event_lines(caplog, "FILTER_COMPLETE"))
        assert stage_lines
        for line in stage_lines:
            assert _rid(line) == _RID, line

    @pytest.mark.asyncio
    async def test_empty_window_complete_empty(self, monkeypatch, caplog):
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {})
        gen = _gen(FakeMemory(rows=[]), TwoCallLLM())
        with caplog.at_level(logging.INFO):
            await gen._run(CHAT, False)
        assert gen.llm.calls == 0                      # LLM не вызывается
        complete = _lines(caplog, "SUMMARY_COMPLETE")
        assert complete and "status=empty" in complete[0]
        assert _rid(complete[0]) == _RID
        assert not _lines(caplog, "SUMMARY_FAILED")

    @pytest.mark.asyncio
    async def test_db_failure_summary_failed(self, monkeypatch, caplog):
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {})
        gen = _gen(FakeMemory(rows=_rows(), error="window"), TwoCallLLM())
        with caplog.at_level(logging.INFO):
            await gen._run(CHAT, False)
        failed = _lines(caplog, "SUMMARY_FAILED")
        assert failed, caplog.text
        assert "stage=db" in failed[0] and "error_type=DatabaseError" in failed[0]
        assert _rid(failed[0]) == _RID
        assert not _lines(caplog, "SUMMARY_COMPLETE")

    @pytest.mark.asyncio
    async def test_llm_failure_summary_failed_http(self, monkeypatch, caplog):
        """B-R1026S7-1/-2: OFF-путь (default) — `SUMMARY_FAILED` несёт реальные
        `model`/`provider`(host) плюс `stage`/`http_status`/`error_type`/
        `attempts` **из реального текста исключения** (атрибут не выставляется);
        сырой текст/URL/ключ не текут (R17)."""
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {})
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", False)
        monkeypatch.setattr(Settings, "SUMMARY_RETRY_ONCE_PAUSE", 0)
        llm = MagicMock()
        llm._chat_model = "model-x"
        llm._base_url = f"https://api.example.com/v1?key={_FAKE_KEY}"
        gen = _gen(FakeMemory(rows=_rows()), llm)
        exc = LLMRateLimitError(                        # реальный формат llm_client
            "LLM rate limited (429) after 3 attempts: "
            "https://api.example.com/v1/chat/completions")
        assert not hasattr(exc, "attempts")             # атрибута нет — только текст
        gen._llm_generate = AsyncMock(side_effect=exc)
        with caplog.at_level(logging.INFO):
            await gen._run(CHAT, False)
        failed = _lines(caplog, "SUMMARY_FAILED")
        assert failed and "stage=run" in failed[0]      # OFF-этап генерации
        assert "model=model-x" in failed[0]             # B-R1026S7-1
        assert "provider=api.example.com" in failed[0]  # host, без схемы/ключа
        assert "http_status=429" in failed[0]
        assert "error_type=LLMRateLimitError" in failed[0]
        assert "attempts=3" in failed[0]                # B-R1026S7-2
        assert "reason=LLMRateLimitError" in failed[0]  # без сырого текста (R17)
        assert "429" not in failed[0].split("reason=")[1].split("|")[0]
        assert "after 3 attempts" not in failed[0]      # R17: текст не логируется
        assert "https://" not in failed[0]              # R17: URL целиком не течёт
        assert _FAKE_KEY not in caplog.text             # R17: ключ не течёт
        assert not _lines(caplog, "SUMMARY_COMPLETE")

    @pytest.mark.asyncio
    async def test_logging_store_failure_best_effort(self, monkeypatch):
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {})
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", False)
        monkeypatch.setattr(Settings, "SUMMARY_COVER_ARTICLE_ENABLED", False)
        rec = _patch_delivery(monkeypatch)

        def _boom(_ctx):
            raise RuntimeError("log store down")

        monkeypatch.setattr(sg, "finish_run", _boom)
        monkeypatch.setattr(sg, "log_summary_start", _boom)
        gen = _gen(FakeMemory(rows=_rows()),
                   MagicMock(generate=AsyncMock(return_value="текст")))
        await gen._run(CHAT, False)                     # не должно бросить
        assert rec["plain"]                             # пайплайн доставлен

    @pytest.mark.asyncio
    async def test_r17_no_secret_in_events(self, monkeypatch, caplog):
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {})
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", False)
        monkeypatch.setattr(Settings, "SUMMARY_COVER_ARTICLE_ENABLED", False)
        _patch_delivery(monkeypatch)
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="текст")
        llm._base_url = f"https://api.example.com/v1?key={_FAKE_KEY}"
        llm._chat_model = "model-x"
        gen = _gen(FakeMemory(rows=_rows()), llm)
        with caplog.at_level(logging.INFO):
            await gen._run(CHAT, False)
        assert _FAKE_KEY not in caplog.text
        assert "api.example.com" not in caplog.text     # успех: host не логируется
        assert "текст" not in caplog.text               # сырой ответ не в логах


# ── SC-04…SC-07: ON-ветка `_run_hybrid_l2` ─────────────────────────────────

class TestHybridLogging:
    @pytest.mark.asyncio
    async def test_hybrid_events_same_run_id(self, monkeypatch, caplog):
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {
            (CHAT, _FLAG): False,
            (CHAT, _HYBRID_FLAG): True,
        })
        monkeypatch.setattr(Settings, "SUMMARY_COVER_ARTICLE_ENABLED", False)
        llm = MagicMock()
        llm.generate = AsyncMock(side_effect=[L1_JSON, L2_JSON])
        llm._chat_model = "model-x"
        llm._base_url = "https://api.example.com/v1"
        gen = _gen(FakeMemory(rows=_rows()), llm)
        sent = []
        monkeypatch.setattr(sg, "send_text",
                            AsyncMock(side_effect=lambda *a, **k: sent.append(a)))

        with caplog.at_level(logging.INFO):
            await gen._run(CHAT, False)

        assert llm.generate.await_count == 2            # L1 + L2: 2-вызовность
        # SC-11: оба этапных вызова коррелируют с событиями по одному run_id.
        for call in llm.generate.await_args_list:
            assert call.kwargs.get("correlation_id") == _RID
        complete = _lines(caplog, "SUMMARY_COMPLETE")
        assert complete and "mode=hybrid_l2" in complete[0]
        assert "status=ok" in complete[0] and "paragraphs=1" in complete[0]
        assert "cover_status=unavailable" in complete[0]
        for name in ("SUMMARY_START", "SUMMARY_COMPLETE", "L1_START",
                     "L1_COMPLETE", "L2_START", "L2_COMPLETE",
                     "FORMAT_START", "FORMAT_COMPLETE"):
            lines = _lines(caplog, name)
            assert lines, name
            for line in lines:
                assert _rid(line) == _RID, line
        assert "channel=plain" in _lines(caplog, "FORMAT_START")[0]
        # S6 (D6): реальная публикация plain → PUBLISH_TEXT_* с тем же run_id;
        # rich-событий нет (канал plain).
        pub_start = _lines(caplog, "PUBLISH_TEXT_START")
        pub_done = _lines(caplog, "PUBLISH_TEXT_COMPLETE")
        assert pub_start and pub_done
        assert "method=sendMessage" in pub_start[0]
        assert "message_id=" in pub_done[0]
        for line in pub_start + pub_done:
            assert _rid(line) == _RID, line
        assert not _lines(caplog, "PUBLISH_RICH_START")
        assert not _lines(caplog, "PUBLISH_RICH_COMPLETE")

    @pytest.mark.asyncio
    async def test_hybrid_l1_not_usable_degraded(self, monkeypatch, caplog):
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {(CHAT, _HYBRID_FLAG): True})

        async def fake_run_l1(**kwargs):
            from services.summary_l1_contract import invalid_result
            return invalid_result("invalid_json")

        monkeypatch.setattr("services.summary_l1_clusterizer.run_l1",
                            fake_run_l1)
        llm = MagicMock()
        llm.generate = AsyncMock(return_value=L2_JSON)
        gen = _gen(FakeMemory(rows=_rows()), llm)
        with caplog.at_level(logging.INFO):
            await gen._run(CHAT, False)
        assert llm.generate.await_count == 0
        complete = _lines(caplog, "SUMMARY_COMPLETE")
        assert complete and "status=degraded" in complete[0]
        assert not _lines(caplog, "FORMAT_START")
        assert not _lines(caplog, "SUMMARY_FAILED")

    @pytest.mark.asyncio
    async def test_hybrid_l2_error_degraded(self, monkeypatch, caplog):
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {(CHAT, _HYBRID_FLAG): True})
        _hybrid_env(monkeypatch)
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="{ не json")
        gen = _gen(FakeMemory(rows=_rows()), llm)
        with caplog.at_level(logging.INFO):
            await gen._run(CHAT, False)
        assert _lines(caplog, "L2_ERROR")
        complete = _lines(caplog, "SUMMARY_COMPLETE")
        assert complete and "status=degraded" in complete[0]
        assert not _lines(caplog, "FORMAT_START")

    @pytest.mark.asyncio
    async def test_hybrid_l2_llm_error_http_details(self, monkeypatch, caplog):
        """L2-провал на ON-пути: `L2_ERROR` с HTTP-статусом, прогон degraded."""
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {(CHAT, _HYBRID_FLAG): True})
        _hybrid_env(monkeypatch)
        llm = MagicMock()
        llm.generate = AsyncMock(
            side_effect=LLMError("server error 502 after 3 attempts"))
        gen = _gen(FakeMemory(rows=_rows()), llm)
        with caplog.at_level(logging.INFO):
            await gen._run(CHAT, False)
        l2_err = _lines(caplog, "L2_ERROR")
        assert l2_err and "http_status=502" in l2_err[0] and _rid(l2_err[0]) == _RID
        assert any("reason=llm_error" in line for line in l2_err)
        complete = _lines(caplog, "SUMMARY_COMPLETE")
        assert complete and "status=degraded" in complete[0]
        assert not _lines(caplog, "FORMAT_START")

    @pytest.mark.asyncio
    async def test_hybrid_package_raise_summary_failed(self, monkeypatch, caplog):
        """Неожиданный сбой этапа пакета → SUMMARY_FAILED (§106/D6), не COMPLETE."""
        _fixed_rid(monkeypatch)
        _patch_chat_limit(monkeypatch, {(CHAT, _HYBRID_FLAG): True})
        _hybrid_env(monkeypatch)

        def _boom(*a, **k):
            raise RuntimeError("package boom")

        monkeypatch.setattr("services.summary_fact_package.build_fact_package",
                            _boom)
        llm = MagicMock()
        llm.generate = AsyncMock(return_value=L2_JSON)
        gen = _gen(FakeMemory(rows=_rows()), llm)
        with caplog.at_level(logging.INFO):
            await gen._run(CHAT, False)
        assert llm.generate.await_count == 0
        failed = _lines(caplog, "SUMMARY_FAILED")
        assert failed and "stage=package" in failed[0]
        assert "error_type=RuntimeError" in failed[0]
        assert _rid(failed[0]) == _RID
        assert not _lines(caplog, "SUMMARY_COMPLETE")

    @pytest.mark.asyncio
    async def test_format_error_has_run_id_and_reason(self, monkeypatch, caplog):
        """S6 (D5): HTML-чанки упали → FORMAT_ERROR + финальный даунгрейд
        (текст без разметки), PUBLISH_TEXT_ERROR не эмитится (доставка удалась)."""
        _fixed_rid(monkeypatch)
        gen = _gen(FakeMemory(), MagicMock())
        doc = {"schema_version": 1, "title": "Т",
               "paragraphs": [{"text": "Абзац.", "emphasis": None}]}
        fallback = []

        async def _fake_send(bot, chat_id, text, **kw):
            if kw.get("parse_mode") == "HTML":
                raise RuntimeError("network down")
            fallback.append(text)
            return MagicMock(message_id=77)

        monkeypatch.setattr(sg, "send_text", _fake_send)
        with caplog.at_level(logging.INFO):
            await gen._deliver_l2_plain(CHAT, doc, _RID)
        err = _lines(caplog, "FORMAT_ERROR")
        assert err and _rid(err[0]) == _RID and "channel=plain" in err[0]
        assert "reason=RuntimeError" in err[0]
        assert not _lines(caplog, "FORMAT_COMPLETE")
        assert fallback                                 # текст не потерян
        assert not _lines(caplog, "PUBLISH_TEXT_ERROR")  # финал удался
        done = _lines(caplog, "PUBLISH_TEXT_COMPLETE")
        assert done and "message_id=77" in done[0]      # первый чанк даунгрейда

    @pytest.mark.asyncio
    async def test_cover_complete_ok_and_format_rich(self, monkeypatch, caplog,
                                                     tmp_path):
        gen = _gen(FakeMemory(), MagicMock())
        gen._resolve_cover_style_text = AsyncMock(return_value="style")
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpeg")
        monkeypatch.setattr(sg, "generate_image_verbose",
                            AsyncMock(return_value=(str(img), "ok")))
        monkeypatch.setattr(sg, "build_cover_media",
                            MagicMock(return_value="MEDIA"))
        monkeypatch.setattr(sg, "send_rich_message", AsyncMock())
        doc = {"schema_version": 1, "title": "Т",
               "paragraphs": [{"text": "Абзац.", "emphasis": None}]}
        ctx = RunContext(run_id=_RID, chat_id=CHAT)
        with caplog.at_level(logging.INFO):
            await gen._deliver_l2_rich(CHAT, doc, "prompt", _RID, ctx=ctx)
        assert ctx.cover_status == "ok"
        assert "status=ok" in _lines(caplog, "COVER_COMPLETE")[0]
        fmt = _lines(caplog, "FORMAT_COMPLETE")
        assert fmt and "channel=rich" in fmt[0] and "paragraphs=1" in fmt[0]
        for name in ("COVER_START", "COVER_COMPLETE", "FORMAT_START",
                     "FORMAT_COMPLETE"):
            assert _rid(_lines(caplog, name)[0]) == _RID

    @pytest.mark.asyncio
    async def test_cover_unavailable_falls_back_to_plain(self, monkeypatch,
                                                         caplog):
        gen = _gen(FakeMemory(), MagicMock())
        gen._resolve_cover_style_text = AsyncMock(return_value="style")
        monkeypatch.setattr(sg, "generate_image_verbose",
                            AsyncMock(return_value=(None, "no_key")))
        monkeypatch.setattr(sg, "send_text", AsyncMock())
        doc = {"schema_version": 1, "title": "Т",
               "paragraphs": [{"text": "Абзац.", "emphasis": None}]}
        ctx = RunContext(run_id=_RID, chat_id=CHAT)
        with caplog.at_level(logging.INFO):
            await gen._deliver_l2_rich(CHAT, doc, "prompt", _RID, ctx=ctx)
        assert ctx.cover_status == "unavailable"
        assert "status=unavailable" in _lines(caplog, "COVER_COMPLETE")[0]
        assert "channel=plain" in _lines(caplog, "FORMAT_START")[0]
        assert not _lines(caplog, "COVER_ERROR")

    @pytest.mark.asyncio
    async def test_cover_error_on_exception(self, monkeypatch, caplog):
        gen = _gen(FakeMemory(), MagicMock())
        gen._resolve_cover_style_text = AsyncMock(return_value="style")
        monkeypatch.setattr(sg, "generate_image_verbose",
                            AsyncMock(side_effect=RuntimeError("boom")))
        monkeypatch.setattr(sg, "send_text", AsyncMock())
        doc = {"schema_version": 1, "title": "Т",
               "paragraphs": [{"text": "Абзац.", "emphasis": None}]}
        ctx = RunContext(run_id=_RID, chat_id=CHAT)
        with caplog.at_level(logging.INFO):
            await gen._deliver_l2_rich(CHAT, doc, "prompt", _RID, ctx=ctx)
        err = _lines(caplog, "COVER_ERROR")
        assert err and _rid(err[0]) == _RID
        assert "error_type=RuntimeError" in err[0]
        assert "reason=RuntimeError" in err[0]
        assert "duration_ms=" in err[0]
        assert "channel=plain" in _lines(caplog, "FORMAT_START")[0]

    @pytest.mark.asyncio
    async def test_legacy_rich_cover_events(self, monkeypatch, caplog,
                                            tmp_path):
        gen = _gen(FakeMemory(), MagicMock())
        gen._resolve_cover_style_text = AsyncMock(return_value="style")
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpeg")
        monkeypatch.setattr(sg, "generate_image_verbose",
                            AsyncMock(return_value=(str(img), "ok")))
        monkeypatch.setattr(sg, "build_cover_media",
                            MagicMock(return_value="MEDIA"))
        monkeypatch.setattr(sg, "send_rich_message", AsyncMock())
        ctx = RunContext(run_id=_RID, chat_id=CHAT)
        with caplog.at_level(logging.INFO):
            await gen._deliver_rich(CHAT, "текст", "prompt", _RID, ctx=ctx)
        assert ctx.cover_status == "ok"
        assert _lines(caplog, "COVER_START") and _lines(caplog, "COVER_COMPLETE")
        assert _rid(_lines(caplog, "COVER_START")[0]) == _RID


# ── SC-07: *_ERROR-ветки L1/L2 несут §109-детали ───────────────────────────

class TestStageErrorDetails:
    @pytest.mark.asyncio
    async def test_l1_error_http_and_attempts(self, caplog):
        async def _boom(_messages):
            raise _HttpErr("upstream", status_code=429, attempts=3)

        with caplog.at_level(logging.INFO):
            result = await run_l1(
                llm=MagicMock(), rows=_rows(), chat_id=CHAT,
                correlation_id=_RID, llm_call=_boom)
        assert not result.usable
        err = _lines(caplog, "L1_ERROR")
        assert err, caplog.text
        line = err[0]
        assert _rid(line) == _RID
        assert "provider=" in line and "model=" in line
        assert "http_status=429" in line and "attempts=3" in line
        assert "error=_HttpErr" in line and "reason=" in line

    @pytest.mark.asyncio
    async def test_l2_error_http_and_attempts(self, caplog):
        async def _boom(_messages):
            raise _HttpErr("upstream", status_code=503, attempts=2)

        package = {
            "schema_version": 1, "status": "ok",
            "threads": [{
                "thread_id": "thread_001", "name": "t", "description": "f",
                "chronology": [{"message_id": 101, "timestamp": 1}],
                "facts": [{"text": "f", "evidence_message_ids": [101]}],
                "evidence_ids": [101], "fragments": [],
            }],
            "unassigned_message_ids": [], "service": {}, "budget": {},
        }
        with caplog.at_level(logging.INFO):
            result = await run_l2(
                MagicMock(), package, service={}, correlation_id=_RID,
                chat_id=CHAT, llm_call=_boom)
        assert not result.usable
        err = _lines(caplog, "L2_ERROR")
        assert err, caplog.text
        line = err[0]
        assert _rid(line) == _RID
        assert "http_status=503" in line and "attempts=2" in line
        assert "error=_HttpErr" in line

    @pytest.mark.asyncio
    async def test_l1_error_real_llm_text_attempts(self, caplog):
        """B-R1026S7-2: L1_ERROR — `attempts` из реального текста llm_client."""
        async def _boom(_messages):
            raise LLMServerError(
                "LLM server error 502 after 3 attempts: https://api.test/v1")

        with caplog.at_level(logging.INFO):
            result = await run_l1(
                llm=MagicMock(), rows=_rows(), chat_id=CHAT,
                correlation_id=_RID, llm_call=_boom)
        assert not result.usable
        err = _lines(caplog, "L1_ERROR")
        assert err, caplog.text
        line = err[0]
        assert _rid(line) == _RID
        assert "http_status=502" in line and "attempts=3" in line
        assert "error=LLMServerError" in line
        assert "https://" not in line                   # R17: URL не течёт

    @pytest.mark.asyncio
    async def test_l2_error_real_llm_text_attempts(self, caplog):
        """B-R1026S7-2: L2_ERROR — `attempts` из реального текста llm_client."""
        async def _boom(_messages):
            raise LLMRateLimitError(
                "LLM rate limited (429) after 3 attempts: https://api.test/v1")

        package = {
            "schema_version": 1, "status": "ok",
            "threads": [{
                "thread_id": "thread_001", "name": "t", "description": "f",
                "chronology": [{"message_id": 101, "timestamp": 1}],
                "facts": [{"text": "f", "evidence_message_ids": [101]}],
                "evidence_ids": [101], "fragments": [],
            }],
            "unassigned_message_ids": [], "service": {}, "budget": {},
        }
        with caplog.at_level(logging.INFO):
            result = await run_l2(
                MagicMock(), package, service={}, correlation_id=_RID,
                chat_id=CHAT, llm_call=_boom)
        assert not result.usable
        err = _lines(caplog, "L2_ERROR")
        assert err, caplog.text
        line = err[0]
        assert _rid(line) == _RID
        assert "http_status=429" in line and "attempts=3" in line
        assert "error=LLMRateLimitError" in line
        assert "https://" not in line                   # R17: URL не течёт


# ── SC-14: dry-run S9 переиспользует контур, без SUMMARY_*/PUBLISH_* ───────

class TestDryRunContour:
    @pytest.mark.asyncio
    async def test_dry_run_stage_events_same_run_id(self, monkeypatch, caplog):
        _patch_chat_limit(monkeypatch, {})
        gen = _real_generator(_dry_rows(), _fake_llm([L1_JSON, L2_JSON]))
        with caplog.at_level(logging.INFO):
            result = await run_summary_test(DRY_CHAT, {"hours": 24},
                                            generator=gen,
                                            correlation_id=_RID, pg=None)
        assert result.status == STATUS_OK
        assert gen.llm.generate.await_count == 2        # 0/0/0 + 2 вызова
        for name in ("L1_START", "L1_COMPLETE", "L2_START", "L2_COMPLETE",
                     "FORMAT_START", "FORMAT_COMPLETE"):
            lines = _lines(caplog, name)
            assert lines, name
            assert _rid(lines[0]) == _RID
        assert "SUMMARY_START" not in caplog.text       # тест ≠ прод-жизненный
        assert "SUMMARY_COMPLETE" not in caplog.text
        assert "SUMMARY_FAILED" not in caplog.text
        assert "PUBLISH_" not in caplog.text            # GATED
        assert "COVER_" not in caplog.text              # обложка не генерируется

    @pytest.mark.asyncio
    async def test_dry_run_format_error_test_code(self, monkeypatch, caplog):
        """L-R1026S7-3: `SUMMARY_TEST_FORMAT_ERROR` — error_type/reason без
        traceback и сырых текстов (R17)."""
        _patch_chat_limit(monkeypatch, {})
        gen = _real_generator(_dry_rows(), _fake_llm([L1_JSON, L2_JSON]))

        def _boom(*a, **k):
            raise RuntimeError("secret formatter text")

        monkeypatch.setattr(str_mod, "format_rich_html", _boom)
        with caplog.at_level(logging.INFO):
            result = await run_summary_test(DRY_CHAT, {"hours": 24},
                                            generator=gen,
                                            correlation_id=_RID, pg=None)
        assert result.status == STATUS_OK               # предпросмотр plain жив
        recs = [r for r in caplog.records
                if r.getMessage().startswith("SUMMARY_TEST_FORMAT_ERROR")]
        assert recs and _RID in recs[0].getMessage()
        assert "error_type=RuntimeError" in recs[0].getMessage()
        assert "reason=formatter_error" in recs[0].getMessage()
        assert recs[0].exc_info is None                 # R17: без traceback
        assert "secret formatter text" not in caplog.text
        assert "FORMAT_START" in caplog.text
        assert "FORMAT_COMPLETE" not in caplog.text
        assert not _lines(caplog, "FORMAT_ERROR")       # тест-код, не прод-событие

    @pytest.mark.asyncio
    async def test_dry_run_window_failure_r17_no_traceback(self, monkeypatch,
                                                           caplog):
        """T-3400 (L-R1026S9-8): окно-ошибка dry-run — error_type без traceback."""
        _patch_chat_limit(monkeypatch, {})
        gen = _real_generator(_dry_rows(), _fake_llm([]))
        gen.build_test_rows = AsyncMock(
            side_effect=RuntimeError("secret raw window text"))
        with caplog.at_level(logging.INFO):
            result = await run_summary_test(DRY_CHAT, {"hours": 24},
                                            generator=gen,
                                            correlation_id=_RID, pg=None)
        assert result.status == STATUS_ERROR
        recs = [r for r in caplog.records
                if r.getMessage().startswith("SUMMARY_TEST_WINDOW_FAILED")]
        assert recs and "error_type=RuntimeError" in recs[0].getMessage()
        assert recs[0].exc_info is None                # R17: без traceback
        assert "secret raw window text" not in caplog.text

    @pytest.mark.asyncio
    async def test_dry_run_no_side_effects_kept(self, monkeypatch):
        _patch_chat_limit(monkeypatch, {})
        gen = _real_generator(_dry_rows(), _fake_llm([L1_JSON, L2_JSON]))
        from services import image_generation, telegram_send
        send_text = MagicMock()
        send_rich = MagicMock()
        gen_image = MagicMock()
        monkeypatch.setattr(telegram_send, "send_text", send_text)
        monkeypatch.setattr(telegram_send, "send_rich_message", send_rich)
        monkeypatch.setattr(image_generation, "generate_image_verbose", gen_image)
        result = await run_summary_test(DRY_CHAT, {"hours": 24}, generator=gen,
                                        correlation_id=_RID, pg=None)
        assert result.status == STATUS_OK
        assert result.publication["status"] == "not_published"
        send_text.assert_not_called()
        send_rich.assert_not_called()
        gen_image.assert_not_called()
        assert gen.memory.writes == 0                   # 0/0/0 сохранены


# ── SC-12/SC-15/SC-16: инварианты ──────────────────────────────────────────

class TestInvariants:
    def test_catalog_zero_delta(self):
        assert len(pc.REGISTRY) == 469
        assert len({f.name for f in dataclasses.fields(Settings)}) == 426
        assert len([s for s in pc.REGISTRY.values()
                    if s.category is not None]) == 444
        assert len(pc.GROUPS) == 100
        assert len(pc._TAB_BY_GROUP) == 98
        assert len(pc.TAB_RULES) == 21

    def test_app_version_bumped(self):
        assert APP_VERSION == "2.58.29"

    def test_publish_events_only_on_real_publication(self):
        """S6 (D6): PUBLISH_* реализованы в живом публикационном контуре; S9
        dry-run (`summary_test_run.py`) публикационных событий не эмитит."""
        for name in ("services/summary_run_log.py",
                     "services/summary_generator.py",
                     "web/app.js"):
            src = (ROOT / name).read_text(encoding="utf-8")
            assert "PUBLISH_RICH" in src, name
            assert "PUBLISH_TEXT" in src, name
        dry = (ROOT / "services/summary_test_run.py").read_text(
            encoding="utf-8")
        assert "PUBLISH_RICH" not in dry, "dry-run S9 не публикует"
        assert "PUBLISH_TEXT" not in dry, "dry-run S9 не публикует"

    def test_forbidden_modules_untouched(self):
        routes = (ROOT / "web/api/routes.py").read_text(encoding="utf-8")
        assert "summary_run_log" not in routes
        assert "logSummary" not in routes
        catalog = (ROOT / "services/param_catalog.py").read_text(
            encoding="utf-8")
        assert "summary_run_log" not in catalog
        for name in ("services/image_generation.py",
                     "services/telegram_send.py"):
            src = (ROOT / name).read_text(encoding="utf-8")
            assert "summary_run_log" not in src, name
