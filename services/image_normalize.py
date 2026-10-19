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
import dataclasses
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

_CODEC: str | None = None


def normalize_enabled() -> bool:
    """env-only киль-свитч контура (default ON; сбой резолва → ON)."""
    try:
        return bool(getattr(settings, "MCA_VISION_NORMALIZE_ENABLED", True))
    except Exception:      # pragma: no cover - конфиг не рвёт вызов
        return True


def configured_max_dimension() -> int:
    """Необязательный потолок большей стороны подготовленной копии
    (`MCA_VISION_NORMALIZE_MAX_DIMENSION`; 0 = без потолка — КОРР №2:
    никакого жёсткого 1024)."""
    try:
        value = int(getattr(settings, "MCA_VISION_NORMALIZE_MAX_DIMENSION", 0))
    except Exception:      # pragma: no cover
        value = 0
    return max(0, value)


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


def _via_pillow(data: bytes, max_dim: int | None) -> bytes | None:
    from PIL import Image, ImageOps
    try:
        Image.MAX_IMAGE_PIXELS = _pixel_cap()
    except Exception:      # pragma: no cover - guard не критичен для вызова
        pass
    with Image.open(io.BytesIO(data)) as im:
        width, height = im.size
        if width <= 0 or height <= 0 or width * height > _pixel_cap():
            return None                       # тот же bomb-guard, что в MCA-19
        im.load()
        # Ориентация EXIF: при перекодировании применяем её (baked), иначе
        # после потери EXIF кадр визуально повернулся бы (КОРР №2).
        im = ImageOps.exif_transpose(im)
        if max_dim and max(im.size) > max_dim:
            im.thumbnail((max_dim, max_dim))
        frame = im.convert("RGB") if im.mode not in ("RGB", "L") else im
        buf = io.BytesIO()
        frame.save(buf, "JPEG", quality=JPEG_QUALITY)
        out = buf.getvalue()
    return out or None


def _via_ffmpeg(data: bytes, max_dim: int | None) -> bytes | None:
    """ffmpeg-бэкенд (прод-вероятный кодек, видео-контур уже им пользуется).

    Вход — bounded временный файл, а не pipe: TIFF и ряд форматов требуют
    seekable-источник и из pipe не декодируются (проверено локально).
    Файл удаляется в finally; содержимое не логируется (R17).
    ``max_dim=None`` — без ресайза (перекодирование в исходном разрешении)."""
    exe = _ffmpeg_path()
    if not exe:
        return None
    cmd = [exe, "-hide_banner", "-loglevel", "error", "-nostdin"]
    tmp_path = None
    proc = None
    try:
        with tempfile.NamedTemporaryFile(delete=False) as fh:
            fh.write(data)
            tmp_path = fh.name
        cmd += ["-i", tmp_path, "-frames:v", "1"]
        if max_dim:
            # `min(...)` не апскейлит; decrease сохраняет пропорции.
            cmd += ["-vf",
                    (f"scale='min({max_dim},iw)':'min({max_dim},ih)':"
                     "force_original_aspect_ratio=decrease")]
        cmd += ["-q:v", "4", "-f", "mjpeg", "pipe:1"]
        proc = subprocess.run(cmd, capture_output=True,
                              timeout=FFMPEG_TIMEOUT_SECONDS)
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
    """bytes → JPEG (декод-фоллбэк/совместимая копия). Никогда не бросает.

    ``max_dimension=None`` — БЕЗ ресайза (перекодирование в исходном
    разрешении, ориентация EXIF применяется); иначе — пропорциональный
    downscale до потолка стороны. None — рубильник OFF / нет кодека / вход не
    декодируется. Проверка «меньше исходного» — на вызывающем."""
    if not data or not normalize_enabled():
        return None
    codec = codec_available()
    if not codec:
        return None
    try:
        if codec == "pillow":
            out = _via_pillow(data, max_dimension)
        else:
            out = _via_ffmpeg(data, max_dimension)
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


# ════════════════════════════════════════════════════════════════════════════
# VISION-ADAPT (19.10.2026, КОРР №2): единый поэтапный preprocessing
# ════════════════════════════════════════════════════════════════════════════
#
# Директива владельца (КОРР №2): решение об оптимизации — ТОЛЬКО от MIME/
# размера/пикселей/фактического payload/лимитов/ответа API; НИКАКОЙ
# классификации контента и формы (фото/мем/скриншот — не различаются), и
# фрагментация НЕ является обязательным этапом обычного распознавания.
#   1) original — влезает (0 перекодирований) ИЛИ лимит неизвестен
#      (пробуем оригинал и адаптируемся по фактическому ответу);
#   2) Этап A — уменьшение веса БЕЗ изменения разрешения (контролируемое
#      перекодирование; гарды: нет выигрыша / прозрачность / анимация /
#      ориентация EXIF);
#   3) Этап B — постепенный ресайз с пропорциями, максимум разрешения в
#      рамках лимитов (без жёсткого 1024; bounded-шаги от фактического
#      payload);
#   4) retry ≤1 — только подтверждённый size/format-отказ (в mca_vision).
# Утилиты фрагментации (`segment_plan`/`plan_segments`/`merge_segment_analyses`
# /`dedup_lines`) сохранены как НЕ-дефолтные инструменты.
# Лимиты — провайдер-агностичные (settings/env), без хардкода OpenRouter/Gemma.

#: Минимальная сторона постепенного ресайза (ниже — не уменьшаем).
MIN_DIMENSION = 256
#: Классы отказа провайдера по тексту ответа (провайдер-агностично).
_REJECTION_HINTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("size", ("payload too large", "request entity too large",
              "request too large", "body too large", "content too large",
              "request payload size", "413")),
    ("context", ("context length", "context window", "maximum context",
                 "max context", "context_length_exceeded",
                 "too many tokens", "token limit", "tokens in the image")),
    ("pixels", ("image too large", "image dimensions", "dimensions too large",
                "resolution too large", "too many pixels", "max dimension",
                "image is too large")),
    ("format", ("unsupported image", "invalid image", "failed to decode",
                "could not decode", "cannot decode", "unsupported media",
                "unsupported format", "invalid_image", "malformed image",
                "corrupt", "unsupported content type", "image format")),
)


@dataclasses.dataclass(frozen=True)
class VisionLimits:
    """Провайдер-агностичная модель лимитов одного Vision-запроса."""
    request_max_bytes: int        # бюджет СЫРЫХ байт (base64 ≈ ×4/3); 0 = неизвестен
    prep_max_pixels: int          # мягкий потолок пикселей копии
    hard_max_pixels: int          # жёсткий bomb-guard (MCA-19)
    segment_window: int           # окно утилиты фрагментации (не дефолт)
    segment_max: int              # потолок числа фрагментов (утилита)
    overlap_ratio: float          # перекрытие фрагментов (утилита, ≥0.10)
    adapt_budget_seconds: float   # общий bounded-бюджет

    @property
    def budget_known(self) -> bool:
        """False — лимит байтов неизвестен: отправляем оригинал и
        адаптируемся по фактическому ответу (КОРР №2, шаг 3)."""
        return int(self.request_max_bytes or 0) > 0

    @property
    def request_max_chars(self) -> int:
        """Оценка бюджета base64-payload (провайдер видит именно его)."""
        return estimate_payload_chars(self.request_max_bytes)


def estimate_payload_chars(data_len: int) -> int:
    """base64-оценка фактического payload (×4/3 + служебная обвязка)."""
    return int(data_len) * 4 // 3 + 256


def _setting(name: str, default):
    try:
        return getattr(settings, name, default)
    except Exception:      # pragma: no cover
        return default


def vision_limits() -> VisionLimits:
    """Лимиты из settings/env (провайдер-агностично, конфигурируемо)."""
    return VisionLimits(
        request_max_bytes=max(0, int(_setting(
            "MCA_VISION_REQUEST_MAX_BYTES", 700_000))),
        prep_max_pixels=int(_setting("MCA_VISION_PREP_MAX_PIXELS", 4_000_000)),
        hard_max_pixels=_pixel_cap(),
        segment_window=int(_setting("VISION_IMAGE_MAX_DIMENSION", 1600)),
        segment_max=int(_setting("MCA_VISION_SEGMENT_MAX", 8)),
        overlap_ratio=max(0.10, float(_setting(
            "MCA_VISION_SEGMENT_OVERLAP_RATIO", 0.12))),
        adapt_budget_seconds=float(_setting(
            "MCA_VISION_ADAPT_BUDGET_SECONDS", 90.0)))


def classify_rejection(text: str) -> str:
    """Класс отказа провайдера из текста ответа: ``size``/``context``/
    ``pixels``/``format``/``""`` (неизвестно). Провайдер-агностично: только
    семантические подсказки, без имён провайдеров/моделей."""
    lowered = str(text or "").lower()
    if not lowered:
        return ""
    for cls, hints in _REJECTION_HINTS:
        if any(h in lowered for h in hints):
            return cls
    return ""


@dataclasses.dataclass(frozen=True)
class VisionPlan:
    """Решение о подготовке изображения к Vision-вызову.

    Стратегии ТОЛЬКО `original` (влезает → 0 перекодирований) и `optimize`
    (Этап A → Этап B). Решение — от MIME/размера/пикселей/payload/лимитов;
    форма/контент не учитываются (КОРР №2). `segments` — зарезервировано под
    НЕ-дефолтные утилиты фрагментации, дефолтный путь его не заполняет."""
    strategy: str                 # original | optimize
    reason: str
    segments: tuple = ()
    payload_chars: int = 0
    pixels: int = 0


def segment_plan(width: int, height: int, *, limits: VisionLimits | None = None
                 ) -> tuple:
    """УТИЛИТА (не дефолтный путь): фрагментация длинного изображения —
    существующий `mca_vision.plan_segments` (вызывается явно)."""
    limits = limits or vision_limits()
    from services import mca_vision
    return tuple(mca_vision.plan_segments(
        width, height, max_dimension=limits.segment_window,
        overlap_ratio=limits.overlap_ratio,
        max_segments=limits.segment_max))


def plan_vision(data: bytes, *, mime: str = "", width: int = 0, height: int = 0,
                limits: VisionLimits | None = None) -> VisionPlan:
    """Выбор стратегии — ТОЛЬКО от MIME/размеров/фактического payload/лимитов.

    original — влезает (0 доп. шагов) ИЛИ лимит неизвестен (пробуем оригинал,
    адаптируемся по фактическому ответу); optimize — заведомо превышает
    (Этап A: вес без ресайза → Этап B: постепенный ресайз)."""
    limits = limits or vision_limits()
    payload_chars = estimate_payload_chars(len(data or b""))
    pixels = max(0, int(width)) * max(0, int(height))
    if not normalize_enabled():
        return VisionPlan("original", reason="normalize_disabled",
                          payload_chars=payload_chars, pixels=pixels)
    if not limits.budget_known:
        return VisionPlan("original", reason="budget_unknown",
                          payload_chars=payload_chars, pixels=pixels)
    fits_payload = payload_chars <= limits.request_max_chars
    fits_pixels = pixels <= limits.prep_max_pixels
    mime_ok = (not mime) or mime in SUPPORTED_PROVIDER_MIMES
    if fits_payload and fits_pixels and mime_ok:
        return VisionPlan("original", reason="fits", payload_chars=payload_chars,
                          pixels=pixels)
    reason = "payload_over" if not fits_payload else "pixels_over"
    if not mime_ok:
        reason = "format_conversion"
    return VisionPlan("optimize", reason=reason, payload_chars=payload_chars,
                      pixels=pixels)


#: Форматы, которые провайдер получает как есть (провайдер-агностичный набор
#: OpenAI-совместимого image_url; остальное конвертируется в JPEG).
SUPPORTED_PROVIDER_MIMES = frozenset({"image/jpeg", "image/png", "image/gif",
                                      "image/webp"})


def _fits(data: bytes, *, limits: VisionLimits) -> bool:
    return estimate_payload_chars(len(data)) <= limits.request_max_chars


def _ceiling() -> int:
    """Псевдоним необязательного потолка (0 = без потолка)."""
    return configured_max_dimension()


def _target_dimensions(width: int, height: int, *, scale: float,
                       limits: VisionLimits) -> tuple[int, int]:
    """Пропорциональные размеры шага (без апскейла, не ниже MIN_DIMENSION,
    в рамках prep-пикселей и необязательного потолка)."""
    floor_w = min(MIN_DIMENSION, width)
    floor_h = min(MIN_DIMENSION, height)
    w = max(floor_w, int(width * scale))
    h = max(floor_h, int(height * scale))
    if w * h > limits.prep_max_pixels:
        shrink = (limits.prep_max_pixels / (w * h)) ** 0.5
        w = max(floor_w, int(w * shrink))
        h = max(floor_h, int(h * shrink))
    ceiling = _ceiling()
    if ceiling and max(w, h) > ceiling:
        shrink = ceiling / max(w, h)
        w = max(floor_w, int(w * shrink))
        h = max(floor_h, int(h * shrink))
    return w, h


def _source_flags(data: bytes) -> tuple[bool, bool]:
    """(прозрачность, анимация) источника. Только Pillow-бэкенд может
    проверить; без него — (False, False): остальные гарды (PNG-альфа по
    IHDR, GIF/WebP на ffmpeg) реализованы без декодера — см. NF-1."""
    if codec_available() != "pillow":
        return False, False
    try:
        from PIL import Image
        with Image.open(io.BytesIO(data)) as im:
            if getattr(im, "n_frames", 1) > 1:
                return False, True
            if im.mode in ("RGBA", "LA"):
                return True, False
            if im.mode == "P" and "transparency" in im.info:
                return True, False
            return False, False
    except Exception:
        return False, False


def _png_has_transparency(data: bytes) -> bool:
    """PNG-альфа БЕЗ декодера (stdlib): color type 4/6 в IHDR или tRNS-чанк.

    Нужна на ffmpeg-бэкенде (Pillow нет): прозрачный PNG нельзя «сплющивать»
    в JPEG вслепую (NF-1)."""
    if len(data) < 33 or data[:8] != b"\x89PNG\r\n\x1a\n" \
            or data[12:16] != b"IHDR":
        return False
    color_type = data[25]
    if color_type in (4, 6):
        return True
    if color_type != 3:
        return False
    offset = 8
    size = len(data)
    while offset + 8 <= size:                       # bounded-скан чанков
        length = int.from_bytes(data[offset:offset + 4], "big")
        chunk_type = data[offset + 4:offset + 8]
        if chunk_type == b"tRNS":
            return True
        if chunk_type == b"IDAT" or length > size:
            return False
        offset += 12 + length
    return False


def _encode_png(data: bytes, max_dimension: int | None) -> bytes | None:
    """PNG-копия (прозрачность сохраняется). Fail-open: нет Pillow/ошибка →
    None (никогда не бросает — NF-1)."""
    try:
        from PIL import Image, ImageOps
    except Exception:      # pragma: no cover - прод-бэкенд без Pillow
        return None
    try:
        try:
            Image.MAX_IMAGE_PIXELS = _pixel_cap()
        except Exception:      # pragma: no cover
            pass
        with Image.open(io.BytesIO(data)) as im:
            if im.size[0] * im.size[1] > _pixel_cap():
                return None
            im.load()
            im = ImageOps.exif_transpose(im)
            if max_dimension and max(im.size) > max_dimension:
                im.thumbnail((max_dimension, max_dimension))
            buf = io.BytesIO()
            im.save(buf, "PNG", optimize=True)
            return buf.getvalue() or None
    except Exception:
        logger.debug("[vision] png encode failed | bytes=%d", len(data),
                     exc_info=True)
        return None


def optimize_to_fit(data: bytes, *, limits: VisionLimits | None = None
                    ) -> bytes | None:
    """Единый поэтапный механизм (КОРР №2): Этап A → Этап B.

    Этап A — уменьшение веса БЕЗ изменения разрешения (контролируемое
    перекодирование); НЕ перекодируем, если нет выигрыша или это ухудшает
    совместимость (прозрачность/анимация/ориентация). Этап B — постепенный
    ресайз с пропорциями и максимумом разрешения в рамках лимитов (без
    жёсткого 1024, bounded-шаги от фактического payload).

    Никогда не бросает; не апскейлит. Для известных снифферу форматов
    возвращает только копию МЕНЬШЕ оригинала (иначе None); на
    неизвестном/экзотическом формате — декод-фоллбэк без гарантии «меньше»
    (эту проверку делает вызывающий контур). NF-1: без Pillow PNG-ветка не
    используется (opaque PNG → JPEG; прозрачный PNG/GIF/WebP — пропуск)."""
    if not data or not normalize_enabled():
        return None
    limits = limits or vision_limits()
    if codec_available() == "":
        return None
    from services import mca_vision
    sniffed = mca_vision.sniff_image(data)
    if sniffed is None:
        # Неизвестный/экзотический формат: декод-фоллбэк (без ресайза) —
        # дальше размер решает вызывающий контур.
        return normalize_jpeg_bytes(data)
    mime, width, height = sniffed
    if width <= 0 or height <= 0 or width * height > limits.hard_max_pixels:
        return None
    pillow = codec_available() == "pillow"
    transparent, animated = _source_flags(data)
    if animated:
        return None                     # анимацию не «сплющиваем» в кадр
    if not pillow:
        # Прод-бэкенд без Pillow (NF-1): анимацию/прозрачность не подтвердить
        # декодером — не кодируем вслепую в JPEG.
        if mime in ("image/gif", "image/webp"):
            return None                 # могут быть анимированы
        if mime == "image/png" and _png_has_transparency(data):
            return None                 # альфу в JPEG сохранить нельзя
    prefer_png = pillow and transparent
    if transparent and not pillow:
        return None                     # (страховка; выше уже отсечено)

    def _encode(data_: bytes, target: int | None) -> bytes | None:
        if prefer_png:
            return _encode_png(data_, target)
        return normalize_jpeg_bytes(data_, max_dimension=target)

    attempts = 0
    max_attempts = 3
    scale = 1.0
    best: bytes | None = None
    while attempts < max_attempts:
        attempts += 1
        if scale >= 1.0:
            target = None                               # Этап A: без ресайза
        else:
            w, h = _target_dimensions(width, height, scale=scale, limits=limits)
            target = max(w, h)
        copy = _encode(data, target)
        if not copy:
            break
        if best is None or len(copy) < len(best):
            best = copy
        if _fits(copy, limits=limits):
            logger.info("[vision] adapt | in=%d | out=%d | scale=%.2f | "
                        "stage=%s", len(data), len(copy), scale,
                        "A" if scale >= 1.0 else "B")
            return copy if len(copy) < len(data) else None
        ratio = (limits.request_max_chars
                 / max(1, estimate_payload_chars(len(copy))))
        if ratio >= 1.0:
            break
        next_scale = scale * max(0.35, min(0.9, ratio ** 0.5))
        if next_scale >= scale * 0.95:
            break
        scale = next_scale
    # Нет копии МЕНЬШЕ оригинала → не перекодируем (гард КОРР №2).
    if best is not None and len(best) < len(data):
        return best
    return None


async def optimize_to_fit_async(data: bytes, *,
                                limits: VisionLimits | None = None
                                ) -> bytes | None:
    """Async-обёртка (декод/ресайз в потоке, event loop не блокируется)."""
    return await asyncio.to_thread(optimize_to_fit, data, limits=limits)


def crop_to_jpeg(data: bytes, box: dict, *, limits: VisionLimits | None = None
                 ) -> bytes | None:
    """Фрагмент (crop) → JPEG в бюджете (для OCR-фрагментации). Не бросает."""
    if not data or not normalize_enabled():
        return None
    limits = limits or vision_limits()
    codec = codec_available()
    if not codec:
        return None
    x = int(box.get("x") or 0)
    y = int(box.get("y") or 0)
    w = int(box.get("w") or 0)
    h = int(box.get("h") or 0)
    if w <= 0 or h <= 0:
        return None
    try:
        if codec == "pillow":
            out = _crop_via_pillow(data, x, y, w, h)
        else:
            out = _crop_via_ffmpeg(data, x, y, w, h)
    except Exception:
        logger.debug("[vision] adapt crop failed | box=%s", box, exc_info=True)
        return None
    if not out:
        return None
    if not _fits(out, limits=limits):
        # Фрагмент всё ещё тяжёлый — прогрессивный downscale фрагмента.
        smaller = optimize_to_fit(out, limits=limits)
        if smaller:
            out = smaller
    return out


async def crop_to_jpeg_async(data: bytes, box: dict, *,
                             limits: VisionLimits | None = None) -> bytes | None:
    return await asyncio.to_thread(crop_to_jpeg, data, box, limits=limits)


def _crop_via_pillow(data: bytes, x: int, y: int, w: int, h: int
                     ) -> bytes | None:
    from PIL import Image
    try:
        Image.MAX_IMAGE_PIXELS = _pixel_cap()
    except Exception:      # pragma: no cover
        pass
    with Image.open(io.BytesIO(data)) as im:
        if im.size[0] * im.size[1] > _pixel_cap():
            return None
        box = (max(0, x), max(0, y), min(im.size[0], x + w),
               min(im.size[1], y + h))
        if box[2] <= box[0] or box[3] <= box[1]:
            return None
        frame = im.crop(box)
        if frame.mode not in ("RGB", "L"):
            frame = frame.convert("RGB")
        buf = io.BytesIO()
        frame.save(buf, "JPEG", quality=JPEG_QUALITY)
        return buf.getvalue() or None


def _crop_via_ffmpeg(data: bytes, x: int, y: int, w: int, h: int
                     ) -> bytes | None:
    exe = _ffmpeg_path()
    if not exe:
        return None
    vf = (f"crop={w}:{h}:{max(0, x)}:{max(0, y)}")
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
    except Exception:
        return None
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:      # pragma: no cover
                pass
    if proc is None or proc.returncode != 0:
        return None
    out = proc.stdout
    if not out or not out.startswith(b"\xff\xd8"):
        return None
    return out
