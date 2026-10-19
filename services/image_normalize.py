# -*- coding: utf-8 -*-
"""POSTGEN-DIAG (19.10.2026): bounded нормализация изображения перед Vision.

Диагноз ACCEPTANCE-94 (прод 2.58.94) + локальная репродукция:

  * `image_postgen_vision=failed/vision_failed` на реальной генерации
    (939495 B): вызов дошёл до провайдера (transport-счётчик harness = 2 =
    проба b1 + пост-ген), провайдер вернул non-2xx (не 401/403/429), но
    статус/класс маскировались (в событии только `vision_failed`). Типовой
    класс для «большого» payload — image-class отказ (400/413/415/422);
    входящее 131641 B работало, исходящее 939495 B — нет.
  * `vision_unreadable` на реальных фото (stage=download): сниффер MCA-19
    отвергает ЛЕГАЛЬНЫЕ JPEG с fill-байтами 0xFF (исправлено в
    `mca_vision.sniff_image`) и вовсе не знает форматов-документов (TIFF),
    которые декодируются существующими в окружении кодеками.

Этот модуль даёт ОДИН bounded нормализатор «bytes → JPEG»:

  * кодек — из УЖЕ существующих в окружении: Pillow (если установлен;
    локальный dev/тесты) либо ffmpeg (в проде им же пользуется видео-контур,
    `handlers/video_download.py`); второго vision-пайплайна/провайдера нет;
  * потолки: `MCA_VISION_NORMALIZE_MAX_DIMENSION` (не апскейл),
    `MCA_VISION_MAX_PIXELS` (decompression-bomb guard и для фоллбэка),
    таймаут ffmpeg-подпроцесса;
  * fail-open: нет кодека / не декодируется / рубильник OFF → None
    (поведение вызывающего не меняется — честный исход сохраняется);
  * R17: байты/декодированный контент не логируются — только класс/размеры.

Киль-свитч `MCA_VISION_NORMALIZE_ENABLED` (env-only, default ON): OFF →
полный паритет прежнего поведения.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import shutil
import subprocess
import tempfile

from config.settings import settings

logger = logging.getLogger(__name__)

#: Качество JPEG-нормализации (реалистичный компромисс размер/детали).
JPEG_QUALITY = 85
#: Бюджет ffmpeg-подпроцесса (секунды): декод+ресайз одного кадра.
FFMPEG_TIMEOUT_SECONDS = 10.0
#: Потолок стороны по умолчанию (env-ручка `MCA_VISION_NORMALIZE_MAX_DIMENSION`).
DEFAULT_MAX_DIMENSION = 1024

_CODEC: str | None = None


def normalize_enabled() -> bool:
    """env-only киль-свитч контура (default ON; сбой резолва → ON)."""
    try:
        return bool(getattr(settings, "MCA_VISION_NORMALIZE_ENABLED", True))
    except Exception:      # pragma: no cover - конфиг не рвёт вызов
        return True


def configured_max_dimension() -> int:
    """Потолок большей стороны нормализуемого JPEG (без апскейла)."""
    try:
        value = int(getattr(settings, "MCA_VISION_NORMALIZE_MAX_DIMENSION",
                            DEFAULT_MAX_DIMENSION))
    except Exception:      # pragma: no cover
        value = DEFAULT_MAX_DIMENSION
    return max(64, value)


def _pillow_available() -> bool:
    try:
        import PIL.Image  # noqa: F401
        return True
    except Exception:
        return False


def _ffmpeg_path() -> str | None:
    try:
        return shutil.which("ffmpeg")
    except Exception:      # pragma: no cover
        return None


def codec_available() -> str:
    """Фактически доступный кодек: ``pillow`` | ``ffmpeg`` | ``""`` (нет).

    Кеш ин-процессный (детект дорогой при каждом вызове не нужен);
    `reset_codec_cache()` — для тестов/админ-действий."""
    global _CODEC
    if _CODEC is None:
        if _pillow_available():
            _CODEC = "pillow"
        elif _ffmpeg_path():
            _CODEC = "ffmpeg"
        else:
            _CODEC = ""
    return _CODEC


def reset_codec_cache() -> None:
    global _CODEC
    _CODEC = None


def _pixel_cap() -> int:
    try:
        from services import mca_gates
        return int(mca_gates.vision_max_pixels())
    except Exception:      # pragma: no cover
        return 25_000_000


def _via_pillow(data: bytes, max_dim: int) -> bytes | None:
    from PIL import Image
    try:
        Image.MAX_IMAGE_PIXELS = _pixel_cap()
    except Exception:      # pragma: no cover - guard не критичен для вызова
        pass
    with Image.open(io.BytesIO(data)) as im:
        width, height = im.size
        if width <= 0 or height <= 0 or width * height > _pixel_cap():
            return None                       # тот же bomb-guard, что в MCA-19
        im.load()
        if max(width, height) > max_dim:
            im.thumbnail((max_dim, max_dim))
        frame = im.convert("RGB") if im.mode not in ("RGB", "L") else im
        buf = io.BytesIO()
        frame.save(buf, "JPEG", quality=JPEG_QUALITY)
        out = buf.getvalue()
    return out or None


def _via_ffmpeg(data: bytes, max_dim: int) -> bytes | None:
    """ffmpeg-бэкенд (прод-вероятный кодек, видео-контур уже им пользуется).

    Вход — bounded временный файл, а не pipe: TIFF и ряд форматов требуют
    seekable-источник и из pipe не декодируются (проверено локально).
    Файл удаляется в finally; содержимое не логируется (R17)."""
    exe = _ffmpeg_path()
    if not exe:
        return None
    # `min(...)` не апскейлит; decrease сохраняет пропорции; первый кадр.
    vf = (f"scale='min({max_dim},iw)':'min({max_dim},ih)':"
          "force_original_aspect_ratio=decrease")
    tmp_path = None
    proc = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(data)
            tmp_path = fh.name
        proc = subprocess.run(
            [exe, "-hide_banner", "-loglevel", "error", "-nostdin",
             "-i", tmp_path, "-frames:v", "1", "-vf", vf,
             "-q:v", "4", "-f", "mjpeg", "pipe:1"],
            capture_output=True, timeout=FFMPEG_TIMEOUT_SECONDS)
    except Exception:      # timeout/OSError — честный fail-open
        return None
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:      # pragma: no cover - файл уже удалён
                pass
    if proc is None or proc.returncode != 0:
        return None
    out = proc.stdout
    if not out or not out.startswith(b"\xff\xd8"):
        return None
    return out


def normalize_jpeg_bytes(data: bytes, *, max_dimension: int | None = None
                         ) -> bytes | None:
    """bytes → bounded JPEG (нормализация/декод-фоллбэк). Никогда не бросает.

    None — рубильник OFF / нет кодека / вход не декодируется. Результат НЕ
    проверяется на «меньше исходного»: это решает вызывающий (фоллбэк входа
    берёт любой JPEG, retry пост-гена — только строго меньший payload)."""
    if not data or not normalize_enabled():
        return None
    codec = codec_available()
    if not codec:
        return None
    limit = int(max_dimension or configured_max_dimension())
    try:
        if codec == "pillow":
            out = _via_pillow(data, limit)
        else:
            out = _via_ffmpeg(data, limit)
    except Exception:
        logger.debug("[vision] normalize failed | codec=%s | bytes=%d",
                     codec, len(data), exc_info=True)
        return None
    if not out:
        return None
    logger.info("[vision] normalize | codec=%s | in=%d | out=%d",
                codec, len(data), len(out))
    return out


async def normalize_jpeg_bytes_async(data: bytes, *,
                                     max_dimension: int | None = None
                                     ) -> bytes | None:
    """Async-обёртка: декод/ресайз не блокирует event loop (thread)."""
    return await asyncio.to_thread(normalize_jpeg_bytes, data,
                                   max_dimension=max_dimension)
