"""Раунд 3 (T-692, AC-B10/FR-B10) — STT: per-request timeout, размерные гейты
провайдеров, транзиентный повтор стратегии (VoiceTranscriber).

Покрытие: transcribe_voice(timeout=120) → strategy.transcribe(timeout=120);
голосовые без timeout → strategy.timeout (10/15); файл > гейта → стратегия
skipped (лог), обе skipped → TranscriptionUnavailable; транзиентный таймаут/
транспорт → ровно 1 повтор (2 вызова), повтор после успеха — 1 вызов;
детерминированная ошибка (HTTP 400/кривой) — БЕЗ повтора.
"""
import asyncio
import os
import time

import pytest

from services import hot_config as hot
from SmartModule.service import (
    EmptyTranscript,
    TranscriptionUnavailable,
    VoiceTranscriber,
)


class _Strategy:
    """Записывает вызовы (file_path, timeout) и разыгрывает сценарий."""

    name = "fake"
    timeout = 10.0
    max_upload_mb = 0.0

    def __init__(self, mode="ok", result="текст", error=None):
        self._mode = mode          # ok | timeout | error | empty
        self._result = result
        self._error = error
        self.calls: list = []

    @property
    def available(self):
        return True

    async def transcribe(self, file_path, *, timeout=None):
        self.calls.append((file_path, timeout))
        if self._mode == "timeout":
            raise asyncio.TimeoutError()
        if self._mode == "error":
            raise self._error
        if self._mode == "empty":
            return ""
        return self._result


class _Boom:
    """Транзиентная транспортная ошибка (как httpx.ConnectTimeout)."""


@pytest.fixture(autouse=True)
def _no_hot_cache():
    old = hot.get_config_cache()
    hot.set_config_cache(None)
    yield
    hot.set_config_cache(old)


@pytest.fixture
def big_file(tmp_path):
    """Файл заданного размера (МБ) на диске."""
    def _make(mb: int):
        path = tmp_path / "voice.mp4"
        with open(path, "wb") as fh:
            fh.write(b"0" * int(mb * 1024 * 1024))
        return str(path)
    return _make


# ── 1. Per-request timeout (AC-B10) ───────────────────────────────────

class TestPerRequestTimeout:
    @pytest.mark.asyncio
    async def test_timeout_kwarg_passed_to_strategy(self):
        s = _Strategy()
        svc = VoiceTranscriber(strategies=(s,))
        assert await svc.transcribe_voice("/tmp/f.mp4", "mp4", timeout=120.0) \
            == "текст"
        assert s.calls == [("/tmp/f.mp4", 120.0)]

    @pytest.mark.asyncio
    async def test_voice_without_timeout_uses_strategy_default(self):
        s = _Strategy()
        svc = VoiceTranscriber(strategies=(s,))
        assert await svc.transcribe_voice("/tmp/f.ogg", "ogg") == "текст"
        assert s.calls == [("/tmp/f.ogg", 10.0)]    # strategy.timeout

    @pytest.mark.asyncio
    async def test_two_strategies_timeout_parametrized(self):
        s1 = _Strategy(mode="timeout")
        s2 = _Strategy()
        svc = VoiceTranscriber(strategies=(s1, s2))
        await svc.transcribe_voice("/tmp/f.mp4", "mp4", timeout=120.0)
        assert s1.calls == [("/tmp/f.mp4", 120.0), ("/tmp/f.mp4", 120.0)]
        assert s2.calls == [("/tmp/f.mp4", 120.0)]


# ── 2. Размерные гейты провайдеров (FR-B10.б) ─────────────────────────

class TestSizeGates:
    @pytest.mark.asyncio
    async def test_over_gate_strategy_skipped(self, big_file, caplog):
        s = _Strategy()
        s.max_upload_mb = 25.0
        svc = VoiceTranscriber(strategies=(s, _Strategy()))
        with caplog.at_level("WARNING", logger="SmartModule.service"):
            text = await svc.transcribe_voice(big_file(30), "mp4", timeout=120.0)
        assert text == "текст"                      # вторая стратегия сработала
        assert s.calls == []                        # первая skipped
        assert any("skipped (file 30 MB > limit 25 MB)" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_both_skipped_raises_unavailable(self, big_file, caplog):
        s1 = _Strategy()
        s1.max_upload_mb = 25.0
        s2 = _Strategy()
        s2.max_upload_mb = 20.0
        svc = VoiceTranscriber(strategies=(s1, s2))
        with pytest.raises(TranscriptionUnavailable):
            await svc.transcribe_voice(big_file(30), "mp4", timeout=120.0)
        assert s1.calls == [] and s2.calls == []
        assert any("skipped" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_small_file_not_gated(self, tmp_path):
        s = _Strategy()
        s.max_upload_mb = 25.0
        svc = VoiceTranscriber(strategies=(s,))
        small = tmp_path / "small.mp4"
        small.write_bytes(b"x" * 1024)
        assert await svc.transcribe_voice(str(small), "mp4") == "текст"
        assert len(s.calls) == 1


# ── 3. Транзиентный повтор (FR-B10.в) ─────────────────────────────────

class TestTransientRetry:
    @pytest.mark.asyncio
    async def test_timeout_retried_once_then_success(self):
        calls = {"n": 0}

        class Flaky(_Strategy):
            timeout = 10.0

            async def transcribe(self, file_path, *, timeout=None):
                calls["n"] += 1
                self.calls.append((file_path, timeout))
                if calls["n"] == 1:
                    raise asyncio.TimeoutError()
                return "со второй"

        svc = VoiceTranscriber(strategies=(Flaky(),))
        assert await svc.transcribe_voice("/tmp/f.mp4", "mp4", timeout=120.0) \
            == "со второй"
        assert calls["n"] == 2                     # 1 стартовая + 1 повтор

    @pytest.mark.asyncio
    async def test_transient_timeout_then_fail_moves_to_next(self):
        s1 = _Strategy(mode="timeout")
        s2 = _Strategy()
        svc = VoiceTranscriber(strategies=(s1, s2))
        assert await svc.transcribe_voice("/tmp/f.mp4", "mp4") == "текст"
        assert len(s1.calls) == 2                  # повтор был
        assert len(s2.calls) == 1

    @pytest.mark.asyncio
    async def test_deterministic_error_not_retried(self):
        err = RuntimeError("HTTP 400 from router")
        s = _Strategy(mode="error", error=err)
        svc = VoiceTranscriber(strategies=(s,))
        with pytest.raises(TranscriptionUnavailable):
            await svc.transcribe_voice("/tmp/f.mp4", "mp4")
        assert len(s.calls) == 1                   # БЕЗ повтора (не транзиент)

    @pytest.mark.asyncio
    async def test_retry_on_transport_like_error(self):
        calls = {"n": 0}

        class _TransportError(Exception):
            pass

        class Flaky(_Strategy):
            async def transcribe(self, file_path, *, timeout=None):
                calls["n"] += 1
                self.calls.append((file_path, timeout))
                if calls["n"] == 1:
                    raise _TransportError()        # маркер «transport»
                return "ок"

        svc = VoiceTranscriber(strategies=(Flaky(),))
        # имя класса «_TransportError» содержит 'transport' → транзиентный
        assert await svc.transcribe_voice("/tmp/f.mp4", "mp4") == "ок"
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_timeout_after_retry_gives_up_to_next(self):
        s1 = _Strategy(mode="timeout")
        s2 = _Strategy()
        svc = VoiceTranscriber(strategies=(s1, s2))
        result = await svc.transcribe_voice("/tmp/f.mp4", "mp4", timeout=120.0)
        assert result == "текст"
        assert len(s1.calls) == 2

    @pytest.mark.asyncio
    async def test_empty_answers_still_empty_transcript(self):
        s1 = _Strategy(mode="empty")
        s2 = _Strategy(mode="empty")
        svc = VoiceTranscriber(strategies=(s1, s2))
        with pytest.raises(EmptyTranscript):
            await svc.transcribe_voice("/tmp/f.mp4", "mp4", timeout=120.0)
        assert len(s1.calls) == 1 and len(s2.calls) == 1
