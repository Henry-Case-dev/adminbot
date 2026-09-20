"""Хотфикс-3 (round10.25, ADR-1025-7 D3) — подготовка аудио перед STT.

Файл больше размерного гейта провайдеров (28 МБ > 25/20) больше НЕ
отбрасывается: ffmpeg извлекает/сжимает **только аудио** в ogg/opus mono
16 kHz ~24 kbps (для транскрипции этого достаточно), а если после сжатия файл
всё ещё превышает лимит — режем на части (fallback-чанкинг). Нет ffmpeg →
честная причина (`reason=no_ffmpeg`), а не тихий провал.

Модуль ничего не знает о стратегиях/Telegram: чистая утилита «путь → пути».
Вызывающий (``VoiceTranscriber``) сам решает, что делать при `no_ffmpeg`.
"""
from __future__ import annotations

import asyncio
import glob
import logging
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

FFMPEG_BIN = "ffmpeg"
_COMPRESS_TIMEOUT_S = 300.0
# ~24 kbps (libopus `-b:a 24k`) → 3000 байт/сек; используется для оценки
# длительности сегмента при fallback-чанкинге.
_BITRATE_BYTES_PER_SEC = 3000
_CHUNK_TARGET_RATIO = 0.8


@dataclass
class AudioPrepResult:
    """Результат подготовки: список путей + честная причина + размеры.

    ``reason``: ``unchanged`` (сжатие не требовалось) | ``compressed`` |
    ``chunked`` | ``no_ffmpeg`` | ``compress_failed`` | ``chunk_failed``.
    ``tmp_paths`` — временные файлы, которые обязан удалить вызывающий
    (после транскрибации ``cleanup()``)."""

    paths: list[str] = field(default_factory=list)
    reason: str = "unchanged"
    orig_mb: float = 0.0
    result_mb: float = 0.0
    tmp_paths: list[str] = field(default_factory=list)
    # Review fix (L-1): каталоги чанкинга (`stt_seg_*`) — их тоже чистим,
    # иначе на каждый чанкованный файл остаётся пустой temp-каталог.
    tmp_dirs: list[str] = field(default_factory=list)

    def cleanup(self) -> None:
        """Удалить временные файлы И каталоги (fail-open: ошибки fs не критичны)."""
        for path in set(self.tmp_paths):
            if not path:
                continue
            try:
                os.remove(path)
            except OSError:
                pass
        for directory in set(self.tmp_dirs):
            if not directory:
                continue
            try:
                shutil.rmtree(directory, ignore_errors=True)
            except Exception:  # pragma: no cover - defensive
                pass


def ffmpeg_available(binary: str = FFMPEG_BIN) -> bool:
    """Есть ли ffmpeg в PATH (никогда не бросает)."""
    try:
        return shutil.which(binary) is not None
    except Exception:  # pragma: no cover - defensive
        return False


def _file_mb(path: str) -> float:
    try:
        return os.path.getsize(path) / (1024.0 * 1024.0)
    except OSError:
        return 0.0


def _run_ffmpeg(binary: str, args: list[str], timeout: float):
    """Sync-обёртка subprocess (тесты подменяют её целиком)."""
    return subprocess.run(
        [binary, *args], stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE, timeout=timeout)


async def _run(binary: str, args: list[str], timeout: float):
    return await asyncio.to_thread(_run_ffmpeg, binary, args, timeout)


def _cleanup(paths) -> None:
    for path in set(paths or []):
        if not path:
            continue
        try:
            os.remove(path)
        except OSError:
            pass


def _cleanup_dir(path: str) -> None:
    try:
        shutil.rmtree(path, ignore_errors=True)
    except Exception:  # pragma: no cover - defensive
        pass


async def _compress(src: str, out: str, ffmpeg_bin: str, timeout: float) -> bool:
    """ffmpeg → ogg/opus mono 16 kHz. True при успехе (файл создан и непуст)."""
    args = [
        "-y", "-i", src, "-vn", "-ac", "1", "-ar", "16000",
        "-c:a", "libopus", "-b:a", "24k", "-f", "ogg", out,
    ]
    try:
        proc = await _run(ffmpeg_bin, args, timeout)
    except Exception:
        return False
    return (getattr(proc, "returncode", 1) == 0
            and os.path.exists(out) and os.path.getsize(out) > 0)


async def _chunk(path: str, max_mb: float, ffmpeg_bin: str,
                 timeout: float) -> tuple[list[str], str | None]:
    """Fallback-чанкинг ogg через segment-muxer; ``([], None)`` при неудаче.

    Оценка длительности сегмента по 24 kbps; проверяем фактический размер
    частей и при превышении пробуем вдвое короче (bounded: 2 попытки).
    При успехе возвращает ``(parts, outdir)`` — каталог ОБЯЗАН быть удалён
    вызывающим (review fix L-1)."""
    for ratio in (_CHUNK_TARGET_RATIO, _CHUNK_TARGET_RATIO / 2):
        seg_seconds = max(
            10, int(max_mb * ratio * 1024 * 1024 / _BITRATE_BYTES_PER_SEC))
        outdir = tempfile.mkdtemp(prefix="stt_seg_")
        pattern = os.path.join(outdir, "part_%03d.ogg")
        args = [
            "-y", "-i", path, "-f", "segment",
            "-segment_time", str(seg_seconds), "-reset_timestamps", "1",
            "-c", "copy", pattern,
        ]
        try:
            proc = await _run(ffmpeg_bin, args, timeout)
            ok = getattr(proc, "returncode", 1) == 0
        except Exception:
            ok = False
        if not ok:
            _cleanup_dir(outdir)
            continue
        parts = sorted(glob.glob(os.path.join(outdir, "part_*.ogg")))
        if not parts:
            _cleanup_dir(outdir)
            continue
        if all(0 < _file_mb(p) <= max_mb for p in parts):
            return parts, outdir
        _cleanup_dir(outdir)
    return [], None


async def extract_audio_for_stt(src: str, max_mb: float, *,
                                ffmpeg_bin: str = FFMPEG_BIN,
                                timeout: float = _COMPRESS_TIMEOUT_S
                                ) -> AudioPrepResult:
    """Подготовить аудио к STT: сжатие → (при необходимости) чанкинг.

    ``max_mb`` — целевой размерный гейт (МБ): укладываем результат под него.
    Возвращает :class:`AudioPrepResult`; временные файлы — в ``tmp_paths``
    (вызывающий чистит через ``cleanup()``). Никогда не бросает."""
    orig_mb = _file_mb(src)
    try:
        limit = float(max_mb)
    except (TypeError, ValueError):
        limit = 0.0
    if limit <= 0 or orig_mb <= limit:
        return AudioPrepResult(paths=[src], reason="unchanged",
                               orig_mb=orig_mb, result_mb=orig_mb)
    if not ffmpeg_available(ffmpeg_bin):
        logger.warning("[stt_prep] ffmpeg unavailable | reason=no_ffmpeg | "
                       "orig_mb=%.1f", orig_mb)
        return AudioPrepResult(paths=[], reason="no_ffmpeg",
                               orig_mb=orig_mb, result_mb=orig_mb)
    fd, out = tempfile.mkstemp(prefix="stt_", suffix=".ogg")
    os.close(fd)
    if not await _compress(src, out, ffmpeg_bin, timeout):
        _cleanup([out])
        logger.warning("[stt_prep] compress failed | reason=compress_failed | "
                       "orig_mb=%.1f", orig_mb)
        return AudioPrepResult(paths=[], reason="compress_failed",
                               orig_mb=orig_mb, result_mb=orig_mb)
    compressed_mb = _file_mb(out)
    if compressed_mb <= limit:
        logger.info("[stt_prep] audio compressed | reason=compressed | "
                    "orig_mb=%.1f | result_mb=%.1f", orig_mb, compressed_mb)
        return AudioPrepResult(paths=[out], reason="compressed",
                               orig_mb=orig_mb, result_mb=compressed_mb,
                               tmp_paths=[out])
    parts, outdir = await _chunk(out, limit, ffmpeg_bin, timeout)
    if not parts:
        _cleanup([out])
        logger.warning("[stt_prep] chunk failed | reason=chunk_failed | "
                       "orig_mb=%.1f | compressed_mb=%.1f",
                       orig_mb, compressed_mb)
        return AudioPrepResult(paths=[], reason="chunk_failed",
                               orig_mb=orig_mb, result_mb=compressed_mb)
    logger.info("[stt_prep] audio chunked | reason=chunked | orig_mb=%.1f | "
                "compressed_mb=%.1f | parts=%d",
                orig_mb, compressed_mb, len(parts))
    return AudioPrepResult(paths=parts, reason="chunked", orig_mb=orig_mb,
                           result_mb=compressed_mb,
                           tmp_paths=[out, *parts],
                           tmp_dirs=[outdir] if outdir else [])
