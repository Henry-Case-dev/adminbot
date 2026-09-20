"""Хотфикс-3 (round10.25, T-2494…T-2499, ADR-1025-7 D3) — STT: извлечение/
сжатие аудио перед транскрибацией.

Падают на старом коде: файл > лимита провайдера просто скипался
(`TranscriptionUnavailable`), helper `extract_audio_for_stt` отсутствовал.
"""
import os
from types import SimpleNamespace

import pytest

from config.settings import Settings
from SmartModule.service import TranscriptionUnavailable, VoiceTranscriber
from SmartModule.transcriber import audio_prep as ap
from SmartModule.transcriber.audio_prep import (
    AudioPrepResult,
    extract_audio_for_stt,
)


def _mkfile(tmp_path, name: str, mb: float) -> str:
    path = tmp_path / name
    path.write_bytes(b"0" * int(mb * 1024 * 1024))
    return str(path)


class _Strategy:
    name = "fake"
    timeout = 10.0
    max_upload_mb = 0.0

    def __init__(self, result="текст", limit=0.0):
        self._result = result
        self.max_upload_mb = limit
        self.calls: list = []

    @property
    def available(self):
        return True

    async def transcribe(self, file_path, *, timeout=None):
        self.calls.append((file_path, timeout))
        return self._result


# ── helper: сжатие / чанкинг / честные причины (T-2494) ──────────────────────

class TestExtractAudioForStt:
    @pytest.mark.asyncio
    async def test_unchanged_when_within_limit(self, tmp_path):
        src = _mkfile(tmp_path, "small.mp4", 1)
        res = await extract_audio_for_stt(src, max_mb=5)
        assert res.reason == "unchanged"
        assert res.paths == [src]
        assert res.tmp_paths == []

    @pytest.mark.asyncio
    async def test_no_ffmpeg_is_honest(self, tmp_path, monkeypatch):
        src = _mkfile(tmp_path, "big.mp4", 3)
        monkeypatch.setattr(ap, "ffmpeg_available", lambda *a, **k: False)
        res = await extract_audio_for_stt(src, max_mb=1)
        assert res.reason == "no_ffmpeg"
        assert res.paths == []

    @pytest.mark.asyncio
    async def test_compressed_and_cleanup(self, tmp_path, monkeypatch):
        src = _mkfile(tmp_path, "big.mp4", 3)
        monkeypatch.setattr(ap, "ffmpeg_available", lambda *a, **k: True)

        def _fake(binary, args, timeout):
            with open(args[-1], "wb") as fh:
                fh.write(b"x" * 100)
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(ap, "_run_ffmpeg", _fake)
        res = await extract_audio_for_stt(src, max_mb=1)
        assert res.reason == "compressed"
        assert len(res.paths) == 1
        assert os.path.exists(res.paths[0])
        res.cleanup()
        assert not os.path.exists(res.paths[0])

    @pytest.mark.asyncio
    async def test_fallback_chunking_cleans_dirs(self, tmp_path, monkeypatch):
        src = _mkfile(tmp_path, "big.mp4", 3)
        max_mb = 0.001
        monkeypatch.setattr(ap, "ffmpeg_available", lambda *a, **k: True)

        def _fake(binary, args, timeout):
            out = args[-1]
            if "segment" in args:
                outdir = os.path.dirname(out)
                for i in range(2):
                    with open(os.path.join(outdir, f"part_{i:03d}.ogg"),
                              "wb") as fh:
                        fh.write(b"y" * 10)
                return SimpleNamespace(returncode=0)
            with open(out, "wb") as fh:      # сжатый всё ещё > лимита
                fh.write(b"y" * 4000)
            return SimpleNamespace(returncode=0)

        monkeypatch.setattr(ap, "_run_ffmpeg", _fake)
        res = await extract_audio_for_stt(src, max_mb=max_mb)
        assert res.reason == "chunked"
        assert len(res.paths) == 2
        assert all(os.path.getsize(p) <= max_mb * 1024 * 1024
                   for p in res.paths)
        # Review fix L-1: каталог чанкинга зарегистрирован в результате.
        assert res.tmp_dirs and all(os.path.isdir(d) for d in res.tmp_dirs)
        res.cleanup()
        assert all(not os.path.exists(p) for p in res.paths)
        assert all(not os.path.exists(d) for d in res.tmp_dirs)

    @pytest.mark.asyncio
    async def test_compress_failed_is_honest(self, tmp_path, monkeypatch):
        src = _mkfile(tmp_path, "big.mp4", 3)
        monkeypatch.setattr(ap, "ffmpeg_available", lambda *a, **k: True)
        monkeypatch.setattr(ap, "_run_ffmpeg",
                            lambda *a, **k: SimpleNamespace(returncode=1))
        res = await extract_audio_for_stt(src, max_mb=1)
        assert res.reason == "compress_failed"
        assert res.paths == []


# ── врезка в VoiceTranscriber (T-2495…T-2497) ────────────────────────────────

class TestVoiceTranscriberIntegration:
    @pytest.mark.asyncio
    async def test_compression_applied_before_gate(self, tmp_path, monkeypatch):
        src = _mkfile(tmp_path, "big.mp4", 3)
        prepared = _mkfile(tmp_path, "prepared.ogg", 0.2)
        prep = AudioPrepResult(paths=[prepared], reason="compressed",
                               orig_mb=3.0, result_mb=0.2,
                               tmp_paths=[prepared])
        monkeypatch.setattr(
            "SmartModule.service.extract_audio_for_stt",
            _async_return(prep))
        s = _Strategy(limit=1.0)
        svc = VoiceTranscriber(strategies=(s,))

        text = await svc.transcribe_voice(src, "mp4", timeout=120.0)

        assert text == "текст"
        assert s.calls and s.calls[0][0] == prepared     # ушёл сжатый файл

    @pytest.mark.asyncio
    async def test_kill_switch_off_uses_original_gate(self, tmp_path,
                                                      monkeypatch):
        src = _mkfile(tmp_path, "big.mp4", 3)
        monkeypatch.setattr(Settings, "STT_AUDIO_COMPRESS_ENABLED", False)
        called = _async_return(AudioPrepResult(paths=["ignored"]))
        monkeypatch.setattr("SmartModule.service.extract_audio_for_stt", called)
        s = _Strategy(limit=1.0)
        svc = VoiceTranscriber(strategies=(s,))

        with pytest.raises(TranscriptionUnavailable):
            await svc.transcribe_voice(src, "mp4", timeout=120.0)

        assert s.calls == []
        assert not called.called                         # сжатие не вызывалось

    @pytest.mark.asyncio
    async def test_no_ffmpeg_falls_back_to_gate(self, tmp_path, monkeypatch,
                                                caplog):
        src = _mkfile(tmp_path, "big.mp4", 3)
        no_ff = AudioPrepResult(paths=[], reason="no_ffmpeg", orig_mb=3.0,
                                result_mb=3.0)
        monkeypatch.setattr(
            "SmartModule.service.extract_audio_for_stt", _async_return(no_ff))
        s = _Strategy(limit=1.0)
        svc = VoiceTranscriber(strategies=(s,))

        with caplog.at_level("INFO", logger="SmartModule.service"):
            with pytest.raises(TranscriptionUnavailable):
                await svc.transcribe_voice(src, "mp4", timeout=120.0)

        assert s.calls == []
        assert any("reason=no_ffmpeg" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_small_file_not_degraded(self, tmp_path, monkeypatch):
        src = _mkfile(tmp_path, "small.mp4", 1)
        called = _async_return(AudioPrepResult(paths=[src]))
        monkeypatch.setattr("SmartModule.service.extract_audio_for_stt", called)
        s = _Strategy(limit=25.0)
        svc = VoiceTranscriber(strategies=(s,))

        assert await svc.transcribe_voice(src, "mp4") == "текст"
        assert not called.called                # в пределах лимита — без сжатия
        assert s.calls[0][0] == src

    @pytest.mark.asyncio
    async def test_partial_chunk_keeps_transcribed(self, tmp_path, monkeypatch,
                                                   caplog):
        """Review fix: сбой одной части чанкинга не теряет остальные."""
        src = _mkfile(tmp_path, "big.mp4", 3)
        part1 = _mkfile(tmp_path, "p1.ogg", 0.2)
        part2 = _mkfile(tmp_path, "p2.ogg", 0.2)
        prep = AudioPrepResult(paths=[part1, part2], reason="chunked",
                               orig_mb=3.0, result_mb=1.0)
        monkeypatch.setattr(
            "SmartModule.service.extract_audio_for_stt",
            _async_return(prep))

        class _Partial(_Strategy):
            async def transcribe(self, file_path, *, timeout=None):
                self.calls.append((file_path, timeout))
                if file_path == part2:
                    raise RuntimeError("HTTP 400 from router")   # не транзиент
                return "первая часть"

        s = _Partial(limit=1.0)
        svc = VoiceTranscriber(strategies=(s,))
        with caplog.at_level("INFO", logger="SmartModule.service"):
            text = await svc.transcribe_voice(src, "mp4", timeout=120.0)

        assert text == "первая часть"          # частичный результат сохранён
        assert any("reason=partial" in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_no_extra_compress_between_gates(self, tmp_path, monkeypatch):
        """Review fix L-2: 22 МБ при гейтах [25, 20] НЕ сжимается — влезает
        в Groq (25); сжатие только если файл больше max(limits)."""
        src = _mkfile(tmp_path, "mid.mp4", 22)
        called = _async_return(AudioPrepResult(paths=[src]))
        monkeypatch.setattr("SmartModule.service.extract_audio_for_stt", called)
        groq = _Strategy(result="из groq", limit=25.0)
        openrouter = _Strategy(result="из openrouter", limit=20.0)
        svc = VoiceTranscriber(strategies=(groq, openrouter))

        assert await svc.transcribe_voice(src, "mp4") == "из groq"
        assert not called.called               # лишнего сжатия нет
        assert openrouter.calls == []          # 20 МБ гейт пропущен

    @pytest.mark.asyncio
    async def test_prep_runs_before_semaphore(self, tmp_path, monkeypatch):
        """Review fix M-1: тяжёлая prep не держит слот STT-семафора."""
        src = _mkfile(tmp_path, "any.mp4", 1)
        order = {"prep": False, "entered": False}

        class _OrderSem:
            async def __aenter__(self):
                assert order["prep"], "prep must complete before semaphore"
                order["entered"] = True
                return self

            async def __aexit__(self, *exc):
                return False

        svc = VoiceTranscriber(strategies=(_Strategy(limit=25.0),))
        svc._semaphore = _OrderSem()

        async def _prep(_self, file_path):
            order["prep"] = True
            return None

        monkeypatch.setattr(VoiceTranscriber, "_prepare_for_stt", _prep)
        assert await svc.transcribe_voice(src, "mp4") == "текст"
        assert order["entered"]


def _async_return(value):
    from unittest.mock import AsyncMock
    return AsyncMock(return_value=value)
