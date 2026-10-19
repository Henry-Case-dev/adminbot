# -*- coding: utf-8 -*-
"""VISION-ADAPT (19.10.2026, КОРР №2) — единый поэтапный preprocessing перед
Vision-вызовами.

Директива владельца (корректировка №2):
  * НИКАКОЙ классификации контента (фото/мем/скриншот/текст) и эвристик по
    форме: решение об оптимизации — ТОЛЬКО от MIME/размера/пикселей/
    фактического payload/лимитов/ответа API;
  * авто-фрагментация НЕ входит в дефолтный путь (`h ≥ 2×w → segments`
    убран); утилиты `segment_plan`/`plan_segments`/`merge_segment_analyses`/
    `dedup_lines` остаются в коде как НЕ-дефолтные инструменты;
  * единый поэтапный механизм: original (влезает → 0 перекодирований) →
    Этап A (уменьшение веса БЕЗ изменения разрешения, с гардами: без выигрыша/
    при потере прозрачности/ориентации — не перекодировать) → Этап B
    (постепенный ресайз с пропорциями, максимум разрешения в рамках лимитов,
    БЕЗ жёсткого 1024, bounded-шаги);
  * лимиты неизвестны (`REQUEST_MAX_BYTES=0`) → отправляем оригинал и
    адаптируемся по фактическому ответу;
  * retry ≤1 только на подтверждённый размер/формат (строго меньшая/
    совместимее копия); 401/403/429/сеть — без повтора; при повторном отказе —
    честная ошибка, а не «успех»;
  * оригинал неизменен; оптимизированная копия не подменяет оригинал.

TEST-LIFECYCLE: CONTRACT owner=VISION-ADAPT
TEST-LIFECYCLE: REGRESSION owner=VISION-ADAPT (лишние перекодирования/
обязательная фрагментация по форме)
"""
from __future__ import annotations

import asyncio
import base64
import io
import json
import random
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import Settings                        # noqa: E402
from services import image_normalize as inorm               # noqa: E402
from services import mca_vision                             # noqa: E402
from services import postgen_vision as pv                   # noqa: E402
from services.mca_vision import (VisionAnalysis,            # noqa: E402
                                 VisionError, validate_image_bytes)

CHAT = -1009001


def _set_env(name: str, value, monkeypatch) -> None:
    for cls in {Settings, type(pv.settings)}:
        if hasattr(cls, name):
            monkeypatch.setattr(cls, name, value)


def _pil():
    return pytest.importorskip("PIL.Image")


def _pil_draw():
    pytest.importorskip("PIL.Image")
    return pytest.importorskip("PIL.ImageDraw")


def _jpeg(size=(800, 600), color=(120, 90, 40), quality=90) -> bytes:
    pil = _pil()
    img = pil.new("RGB", size, color)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _smooth_jpeg(size=(1600, 1200), quality=97) -> bytes:
    """Гладкое изображение: Этап A (кодирование) уменьшает без ресайза."""
    pil = _pil()
    img = pil.linear_gradient("L").resize(size)
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _noisy_jpeg(size=(3000, 2200), quality=95, seed=5) -> bytes:
    pil = _pil()
    rnd = random.Random(seed)
    img = pil.frombytes("L", size, rnd.randbytes(size[0] * size[1]))
    buf = io.BytesIO()
    img.convert("RGB").save(buf, "JPEG", quality=quality)
    return buf.getvalue()


def _bar_color(i: int) -> tuple:
    return ((37 * i + 17) % 256, (91 * i + 53) % 256, (151 * i + 101) % 256)


_LONG_CACHE: dict = {}


def _long_screenshot(n_lines: int = 24, width: int = 800, line_h: int = 120):
    """Длинный скриншот: детерминированный шум-фон + полосы-«строки»."""
    key = (n_lines, width, line_h)
    if key in _LONG_CACHE:
        return _LONG_CACHE[key]
    pil = _pil()
    draw_mod = _pil_draw()
    height = n_lines * line_h
    rnd = random.Random(7)
    img = pil.frombytes("L", (width, height),
                        rnd.randbytes(width * height)).convert("RGB")
    draw = draw_mod.Draw(img)
    colors, lines = [], []
    for i in range(n_lines):
        color = _bar_color(i)
        colors.append(color)
        lines.append(f"LINE-{i:03d}")
        y0 = i * line_h + line_h // 6
        draw.rectangle([12, y0, width - 12, y0 + line_h // 2], fill=color)
    buf = io.BytesIO()
    img.save(buf, "PNG")
    out = (buf.getvalue(), lines, colors)
    _LONG_CACHE[key] = out
    return out


def _bar_run(img, color, *, tolerance: int = 40) -> int:
    """Длиннейшая непрерывная серия строк, где центр — цвет полосы."""
    width, height = img.size
    xs = [width // 2, width // 4, (3 * width) // 4]
    best = run = 0
    for y in range(0, height, 2):
        match = 0
        for x in xs:
            r, g, b = img.getpixel((x, y))[:3]
            if max(abs(r - color[0]), abs(g - color[1]),
                   abs(b - color[2])) <= tolerance:
                match += 1
        if match >= 2:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return best


class OcrTransport:
    """Контрактный мок: «читает» полосы-строки; строка читается, если полоса
    ≥ ``min_rows`` серии И ширина кадра ≥ ``min_width`` (иначе — «принято, но
    текст потерян»)."""

    def __init__(self, truth, colors, *, min_rows: int = 16,
                 min_width: int = 0, fail_status: int | None = None,
                 fail_first: int = 0, fail_message: str = "image too large"):
        self.truth = list(truth)
        self.colors = list(colors)
        self.min_rows = min_rows
        self.min_width = min_width
        self.fail_status = fail_status
        self.fail_first = fail_first
        self.fail_message = fail_message
        self.calls: list[dict] = []

    def read(self, raw: bytes) -> list[str]:
        pil = _pil()
        img = pil.open(io.BytesIO(raw)).convert("RGB")
        return [self.truth[i] for i, color in enumerate(self.colors)
                if _bar_run(img, color) >= self.min_rows]

    async def __call__(self, url, *, payload=None, headers=None, timeout=None):
        part = payload["messages"][1]["content"][1]["image_url"]["url"]
        raw = base64.b64decode(part.split(",", 1)[1])
        self.calls.append({"bytes": len(raw), "chars": len(part)})
        if self.fail_status and len(self.calls) <= self.fail_first:
            message = self.fail_message
            if self.fail_status >= 500:
                message = "internal server error"
            elif self.fail_status == 429:
                message = "rate limit exceeded"
            return self.fail_status, {"error": {"message": message}}
        found = self.read(raw)
        body = {"choices": [{"message": {"content": json.dumps(
            {"ocr_blocks": [{"text": t} for t in found],
             "visual_description": f"кадр с {len(found)} строками",
             "uncertainty": []}, ensure_ascii=False)}}],
            "usage": {}}
        return 200, body


async def _state_ok(chat_id=None):
    return SimpleNamespace(effective_enabled=True, capability="ok",
                           reason="vision_ok", visible_reason="ok")


@pytest.fixture()
def vision_env(monkeypatch):
    monkeypatch.setattr(mca_vision, "resolve_effective_state", _state_ok)
    monkeypatch.setattr(mca_vision, "route_config_problem", lambda route: "")
    monkeypatch.setattr(mca_vision, "api_key_for", lambda route: "test-key")
    yield


# ═════════ 1. Решение — ТОЛЬКО от MIME/размеров/payload/лимитов ════════════


class TestPlanStrategy:
    def test_original_when_fits_and_no_codec_touch(self, monkeypatch):
        """Влезает → original; кодек НЕ вызывается (0 перекодирований)."""
        def _boom(*a, **kw):
            raise AssertionError("кодек не должен вызываться для fits-входа")
        monkeypatch.setattr(inorm, "normalize_jpeg_bytes", _boom)
        data = _jpeg((800, 600), quality=70)
        plan = inorm.plan_vision(data, mime="image/jpeg", width=800, height=600)
        assert plan.strategy == "original"
        assert plan.reason
        assert plan.segments == ()

    def test_shape_does_not_affect_decision(self):
        """ФОРМА не влияет: длинный, но влезающий скриншот → original."""
        data, _lines, _colors = _long_screenshot()
        limits = inorm.vision_limits()
        # бюджеты, при которых 3 МБ PNG влезает
        plan = inorm.plan_vision(
            data, mime="image/png", width=800, height=2880,
            limits=type(limits)(**{**limits.__dict__,
                                  "request_max_bytes": len(data) * 2,
                                  "prep_max_pixels": 10_000_000}))
        assert plan.strategy == "original"

    def test_no_segments_strategy_for_long_heavy(self):
        """КОРР №2: авто-фрагментация по форме убрана из дефолтного пути."""
        data, _lines, _colors = _long_screenshot()
        plan = inorm.plan_vision(data, mime="image/png", width=800,
                                 height=2880)
        assert plan.strategy == "optimize"
        assert plan.segments == ()

    def test_optimize_when_payload_over(self):
        limits = inorm.vision_limits()
        big = b"\xff\xd8" + b"\x00" * (limits.request_max_bytes + 10)
        plan = inorm.plan_vision(big, mime="image/jpeg", width=1024,
                                 height=768, limits=limits)
        assert plan.strategy == "optimize"

    def test_unknown_budget_sends_original(self, monkeypatch):
        """Лимиты неизвестны (0) → оригинал, адаптация по факт. ответу."""
        _set_env("MCA_VISION_REQUEST_MAX_BYTES", 0, monkeypatch)
        data, _lines, _colors = _long_screenshot()
        plan = inorm.plan_vision(data, mime="image/png", width=800,
                                 height=2880)
        assert plan.strategy == "original"

    def test_kill_switch_off_is_original_only(self, monkeypatch):
        _set_env("MCA_VISION_NORMALIZE_ENABLED", False, monkeypatch)
        data, _lines, _colors = _long_screenshot()
        plan = inorm.plan_vision(data, mime="image/png", width=800,
                                 height=2880)
        assert plan.strategy == "original"

    def test_small_image_never_upscaled(self):
        data = _jpeg((64, 48))
        limits = inorm.vision_limits()
        out = inorm.optimize_to_fit(data, limits=limits)
        if out is not None:
            mime, w, h = mca_vision.sniff_image(out)
            assert mime == "image/jpeg" and w <= 64 and h <= 48


# ═════════ 2. Этап A: вес без изменения разрешения (+гарды) ════════════════


class TestStageA:
    def test_encode_without_resize(self):
        limits = inorm.vision_limits()
        data = _smooth_jpeg((1600, 1200), quality=97)
        out = inorm.optimize_to_fit(data, limits=limits)
        assert out is not None
        mime, w, h = mca_vision.sniff_image(out)
        assert mime == "image/jpeg" and (w, h) == (1600, 1200)
        assert len(out) < len(data)

    def test_skipped_when_no_gain(self, monkeypatch):
        """Нет выигрыша → НЕ перекодировать (None; оригинал уходит как есть)."""
        async def _bigger(data, *, max_dimension=None):
            return data + b"\x00" * 16
        monkeypatch.setattr(inorm, "normalize_jpeg_bytes_async", _bigger)
        monkeypatch.setattr(inorm, "normalize_jpeg_bytes",
                            lambda data, *, max_dimension=None:
                            data + b"\x00" * 16)
        out = inorm.optimize_to_fit(_noisy_jpeg((1200, 900), quality=97),
                                    limits=inorm.vision_limits())
        assert out is None

    def test_transparency_not_flattened(self):
        """PNG с прозрачностью не превращается в JPEG (потеря альфы)."""
        pil = _pil()
        img = pil.new("RGBA", (400, 300), (10, 20, 30, 0))
        buf = io.BytesIO()
        img.save(buf, "PNG")
        data = buf.getvalue()
        out = inorm.optimize_to_fit(data, limits=inorm.vision_limits())
        if out is not None:
            mime, _w, _h = mca_vision.sniff_image(out)
            assert mime == "image/png"              # не JPEG
            reopened = pil.open(io.BytesIO(out))
            assert reopened.mode in ("RGBA", "LA", "P")

    def test_exif_orientation_preserved(self):
        """Ориентация EXIF не теряется при Этапе A (baked/сохранена)."""
        pil = _pil()
        image_ops = pytest.importorskip("PIL.ImageOps")
        img = pil.new("RGB", (100, 200), (200, 30, 30))
        exif = pil.Exif()
        exif[0x0112] = 6                            # поворот 90°
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95, exif=exif.tobytes())
        data = buf.getvalue()
        out = inorm.optimize_to_fit(data, limits=inorm.vision_limits())
        assert out is not None
        with pil.open(io.BytesIO(data)) as src:
            expected = image_ops.exif_transpose(src).size
        with pil.open(io.BytesIO(out)) as dst:
            actual = image_ops.exif_transpose(dst).size
        assert actual == expected                   # визуальная ориентация та же


# ═════════ 3. Этап B: постепенный ресайз, без жёсткого 1024 ════════════════


class TestStageB:
    def test_budget_driven_no_1024_cap(self, monkeypatch):
        """Щедрый бюджет → разрешение выше 1024 (нет жёсткого капа)."""
        _set_env("MCA_VISION_REQUEST_MAX_BYTES", 2_000_000, monkeypatch)
        _set_env("MCA_VISION_PREP_MAX_PIXELS", 8_000_000, monkeypatch)
        limits = inorm.vision_limits()
        data = _noisy_jpeg((3000, 2200), quality=95)
        out = inorm.optimize_to_fit(data, limits=limits)
        assert out is not None
        _mime, w, h = mca_vision.sniff_image(out)
        assert max(w, h) > 1024                     # НЕ 1024-кап
        assert len(out) <= limits.request_max_bytes

    def test_downscale_proportional_bounded(self, monkeypatch):
        _set_env("MCA_VISION_PREP_MAX_PIXELS", 250_000, monkeypatch)
        limits = inorm.vision_limits()
        data = _noisy_jpeg((1600, 1200), quality=90)
        calls = {"n": 0}
        orig = inorm.normalize_jpeg_bytes

        def _count(data, *, max_dimension=None):
            calls["n"] += 1
            return orig(data, max_dimension=max_dimension)

        monkeypatch.setattr(inorm, "normalize_jpeg_bytes", _count)
        out = inorm.optimize_to_fit(data, limits=limits)
        assert out is not None
        _mime, w, h = mca_vision.sniff_image(out)
        assert w * h <= 250_000
        assert abs((w / h) - (1600 / 1200)) < 0.06
        assert calls["n"] <= 4                      # bounded-шаги

    def test_fail_open_without_codec(self, monkeypatch):
        monkeypatch.setattr(inorm, "codec_available", lambda: "")
        assert inorm.optimize_to_fit(_jpeg(), limits=inorm.vision_limits()) \
            is None


# ═════════ 4. analyze_adaptive: единый конвейер (без фрагментации) ═════════


class TestAnalyzeAdaptive:
    @pytest.mark.asyncio
    async def test_original_single_call_byte_parity(self, vision_env):
        data = _jpeg((800, 600), quality=70)
        img = validate_image_bytes(data)
        t = OcrTransport([], [])
        out = await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=t)
        assert len(t.calls) == 1
        assert t.calls[0]["bytes"] == len(data)     # байт-в-байт оригинал
        assert out.status in ("ready", "no_text")
        assert img.data == data                     # оригинал неизменен

    @pytest.mark.asyncio
    async def test_long_screenshot_a_b_single_call(self, vision_env):
        """Длинный скриншот: A→B, ОДИН запрос, без авто-фрагментации;
        мелкий текст сохраняется (Этап A/B не убивает читаемость фикстуры)."""
        data, truth, colors = _long_screenshot()
        img = validate_image_bytes(data)
        t = OcrTransport(truth, colors)
        out = await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=t)
        limits = inorm.vision_limits()
        assert len(t.calls) == 1                    # НЕ фрагментируем
        assert t.calls[0]["bytes"] < len(data)      # локальная оптимизация была
        assert t.calls[0]["chars"] <= limits.request_max_chars
        got = [b["text"] for b in out.ocr_blocks]
        assert got == truth                         # порядок + полный состав
        assert img.data == data                     # оригинал неизменен

    @pytest.mark.asyncio
    async def test_negative_accepted_but_text_lost(self, vision_env,
                                                   monkeypatch):
        """«200, но текст потерян» ≠ успех: при вынужденном глубоком сжатии
        строки не выдумываются, покрытие честно неполное (метрика честности)."""
        _set_env("MCA_VISION_REQUEST_MAX_BYTES", 200_000, monkeypatch)
        data, truth, colors = _long_screenshot()
        img = validate_image_bytes(data)
        t = OcrTransport(truth, colors)
        out = await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=t)
        got = [b["text"] for b in out.ocr_blocks]
        assert set(got) <= set(truth)               # ничего не выдумано
        assert len(got) < len(truth)                # и не все восстановлены
        assert len(t.calls) == 1                    # без фрагментации

    @pytest.mark.asyncio
    async def test_pipeline_never_calls_fragmentation(self, vision_env,
                                                      monkeypatch):
        """КОРР №2: дефолтный путь НЕ вызывает crop/фрагментацию."""
        async def _boom(*a, **kw):
            raise AssertionError("фрагментация не должна вызываться")
        monkeypatch.setattr(inorm, "crop_to_jpeg_async", _boom)
        data, truth, colors = _long_screenshot()
        img = validate_image_bytes(data)
        t = OcrTransport(truth, colors)
        out = await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=t)
        assert out.status in ("ready", "no_text")

    @pytest.mark.asyncio
    async def test_unknown_budget_tries_original_first(self, vision_env,
                                                       monkeypatch):
        """Лимиты неизвестны → первый запрос — оригинал (0 перекодирований)."""
        _set_env("MCA_VISION_REQUEST_MAX_BYTES", 0, monkeypatch)
        data, truth, colors = _long_screenshot()
        img = validate_image_bytes(data)
        t = OcrTransport(truth, colors)
        await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=t)
        assert len(t.calls) == 1
        assert t.calls[0]["bytes"] == len(data)

    @pytest.mark.asyncio
    async def test_optimized_copy_never_replaces_original(self, vision_env):
        """Оптимизированная копия не подменяет оригинал (вход не мутируется)."""
        data = _noisy_jpeg((3000, 2200), quality=95)
        img = validate_image_bytes(data)
        snapshot = bytes(img.data)
        t = OcrTransport([], [])
        await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=t)
        assert img.data == snapshot and len(t.calls) == 1


# ═════════ 5. Retry: только size/format, ≤1, не идентичный ═════════════════


class TestAdaptiveRetry:
    @pytest.mark.asyncio
    async def test_retry_on_size_class_with_smaller_copy(self, vision_env):
        data = _jpeg((1200, 900), quality=97)
        img = validate_image_bytes(data)
        t = OcrTransport([], [], fail_status=400, fail_first=1)
        out = await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=t)
        assert len(t.calls) == 2
        assert t.calls[1]["bytes"] < t.calls[0]["bytes"]   # строго другая копия
        assert out.status in ("ready", "no_text")

    @pytest.mark.asyncio
    async def test_no_retry_on_5xx_429_401(self, vision_env):
        for status, expect_reason in ((500, "vision_failed"),
                                      (429, "vision_rate_limited"),
                                      (401, "vision_unavailable")):
            img = validate_image_bytes(_jpeg((800, 600)))
            t = OcrTransport([], [], fail_status=status, fail_first=99)
            with pytest.raises(VisionError) as ei:
                await mca_vision.analyze_adaptive(img, chat_id=CHAT,
                                                  transport=t)
            assert ei.value.reason == expect_reason
            assert len(t.calls) == 1

    @pytest.mark.asyncio
    async def test_no_retry_on_network_error(self, vision_env):
        import httpx
        data = _jpeg((800, 600))
        img = validate_image_bytes(data)

        class _Net(OcrTransport):
            async def __call__(self, url, *, payload=None, headers=None,
                               timeout=None):
                self.calls.append({"bytes": 0, "chars": 0})
                raise httpx.ConnectError("boom")

        t = _Net([], [])
        with pytest.raises(VisionError) as ei:
            await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=t)
        assert ei.value.reason == "vision_unavailable"
        assert len(t.calls) == 1

    @pytest.mark.asyncio
    async def test_no_identical_retry(self, vision_env, monkeypatch):
        async def _same(data, *, max_dimension=None):
            return data
        monkeypatch.setattr(inorm, "normalize_jpeg_bytes_async", _same)
        img = validate_image_bytes(_jpeg((800, 600), quality=70))
        t = OcrTransport([], [], fail_status=400, fail_first=1)
        with pytest.raises(VisionError):
            await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=t)
        assert len(t.calls) == 1

    def test_rejection_classes_from_response(self):
        assert inorm.classify_rejection("image too large") == "pixels"
        assert inorm.classify_rejection(
            "This model's maximum context length is 4096 tokens") == "context"
        assert inorm.classify_rejection("payload too large") == "size"
        assert inorm.classify_rejection("unsupported image format") == "format"
        assert inorm.classify_rejection("some other error") == ""

    @pytest.mark.asyncio
    async def test_detail_carries_rejection_class(self, vision_env):
        t = OcrTransport([], [], fail_status=400, fail_first=99)
        img = validate_image_bytes(_jpeg((800, 600)))
        with pytest.raises(VisionError) as ei:
            await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=t)
        assert "http_400" in ei.value.detail
        assert "/pixels" in ei.value.detail


# ═════════ 6. Утилиты фрагментации (НЕ дефолтный путь) ═════════════════════


class TestFragmentUtilities:
    def test_segment_plan_utility_coverage_overlap(self):
        limits = inorm.vision_limits()
        segs = inorm.segment_plan(800, 2880, limits=limits)
        assert len(segs) >= 2
        assert segs[0]["y"] == 0
        assert segs[-1]["y"] + segs[-1]["h"] == 2880     # полное покрытие
        window = segs[0]["h"]
        for a, b in zip(segs, segs[1:]):
            assert b["y"] > a["y"]
            assert (a["y"] + a["h"]) - b["y"] >= int(window * 0.10)

    def test_segment_plan_reuses_plan_segments(self):
        limits = inorm.vision_limits()
        mine = inorm.segment_plan(800, 2880, limits=limits)
        theirs = mca_vision.plan_segments(
            800, 2880, max_dimension=limits.segment_window,
            overlap_ratio=limits.overlap_ratio,
            max_segments=limits.segment_max)
        assert [dict(s) for s in mine] == [dict(s) for s in theirs]

    @pytest.mark.asyncio
    async def test_merge_segment_analyses_all_lines_no_loss(self):
        """Утилита merge: crop→«распознавание»→dedup_lines без потерь."""
        data, truth, colors = _long_screenshot()
        limits = inorm.vision_limits()
        segs = inorm.segment_plan(800, 2880, limits=limits)
        t = OcrTransport(truth, colors)
        analyses = []
        for seg in segs:
            crop = await inorm.crop_to_jpeg_async(data, seg, limits=limits)
            assert crop
            lines = t.read(crop)
            analyses.append(VisionAnalysis(
                "ready", [{"text": x} for x in lines],
                f"фрагмент с {len(lines)} строками", [], None))
        merged = mca_vision.merge_segment_analyses(
            analyses, expected=len(segs), covered=len(segs))
        got = [b["text"] for b in merged.ocr_blocks]
        assert got == truth                              # порядок + полный состав


# ═════════ 7. Метрики 7 кейсов (без авто-фрагментации) ═════════════════════


class TestFixtureMetrics:
    @pytest.mark.asyncio
    async def test_fixture_set_metrics_and_honesty(self, vision_env):
        """Харнесс: success/OCR-качество/латентность/запросы; «200, но текст
        потерян» фиксируется как метрика честности, а не «успех»."""
        cases = []
        data, truth, colors = _long_screenshot()
        cases.append(("long_screenshot", data, truth, colors))
        meme, m_truth, m_colors = _meme_fixture()
        cases.append(("meme", meme, m_truth, m_colors))
        cases.append(("large_photo", _noisy_jpeg((3000, 2200), quality=95),
                      [], []))
        cases.append(("large_photo_strict_provider",
                      _noisy_jpeg((3000, 2200), quality=95), [], []))
        cases.append(("tiff_document", _tiff(), [], []))
        cases.append(("fillbyte_jpeg", _fillbyte_jpeg(), [], []))
        cases.append(("small_photo", _noisy_jpeg((800, 600), quality=80,
                                                 seed=9), [], []))

        metrics = []
        for name, blob, truth, colors in cases:
            try:
                img = await mca_vision.validate_or_normalize(blob)
            except VisionError as exc:
                metrics.append({"case": name,
                                "prepare_error": exc.reason})
                continue
            limit = 450_000 if "strict" in name else 1_000_000
            t = OcrTransport(truth, colors)
            t_limit = limit

            class _Strict(OcrTransport):
                async def __call__(self, url, *, payload=None, headers=None,
                                   timeout=None):
                    part = payload["messages"][1]["content"][1]["image_url"][
                        "url"]
                    if len(part) > t_limit:
                        self.calls.append({"bytes": 0, "chars": len(part)})
                        return 413, {"error": {"message": "payload too large"}}
                    return await super().__call__(url, payload=payload,
                                                  headers=headers,
                                                  timeout=timeout)

            t = _Strict(truth, colors)
            started = time.monotonic()
            try:
                out = await mca_vision.analyze_adaptive(img, chat_id=CHAT,
                                                        transport=t)
                error = ""
            except VisionError as exc:
                out, error = None, exc.reason
            ms = int((time.monotonic() - started) * 1000)
            got = [b["text"] for b in out.ocr_blocks] if out else []
            recovered = (round(len([x for x in truth if x in got]) / len(truth),
                               3) if truth else None)
            metrics.append({
                "case": name, "status": getattr(out, "status", None),
                "error": error, "calls": len(t.calls), "ms": ms,
                "ocr_recovered": recovered,
                "honest": (not error and set(got) <= set(truth)),
                "analysis_delivered": bool(out) and not error,
            })
        print("ADAPT-METRICS " + json.dumps(metrics, ensure_ascii=False))
        for m in metrics:
            assert m.get("prepare_error") is None, m
            assert m["analysis_delivered"], m            # анализ доставлен
            assert m["honest"], m                        # без выдуманных строк
        # без авто-фрагментации: длинный скриншот — ровно 1 запрос
        long_m = metrics[0]
        assert long_m["calls"] == 1
        # честная фиксация качества OCR (метрика, а не «успех» по 200)
        assert long_m["ocr_recovered"] is not None and \
            long_m["ocr_recovered"] <= 1.0
        # мем влезает → 1 запрос, все строки
        assert metrics[1]["calls"] == 1 and metrics[1]["ocr_recovered"] == 1.0


def _meme_fixture():
    pil = _pil()
    draw_mod = _pil_draw()
    width, height, line_h = 900, 600, 120
    img = pil.new("RGB", (width, height), (250, 250, 250))
    draw = draw_mod.Draw(img)
    colors, lines = [], []
    for i in range(4):
        color = _bar_color(i + 200)
        colors.append(color)
        lines.append(f"MEME-{i:02d}")
        y0 = 20 + i * line_h
        draw.rectangle([20, y0, width - 20, y0 + line_h // 2], fill=color)
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=90)
    return buf.getvalue(), lines, colors


def _tiff(size=(1200, 900)) -> bytes:
    pil = _pil()
    img = pil.new("RGB", size, (90, 140, 200))
    buf = io.BytesIO()
    img.save(buf, "TIFF")
    return buf.getvalue()


def _transparent_png() -> bytes:
    """PNG с альфой (RGBA) — гард «не сплющивать в JPEG»."""
    pil = _pil()
    draw_mod = _pil_draw()
    img = pil.new("RGBA", (900, 700), (10, 20, 30, 0))
    draw = draw_mod.Draw(img)
    draw.rectangle([50, 50, 850, 650], fill=(200, 50, 50, 255))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def _animated_gif() -> bytes:
    """Анимированный GIF — на ffmpeg-пути не должен «сплющиваться»."""
    pil = _pil()
    frames = [pil.new("RGB", (600, 400), (i * 40 % 256, 60, 120))
              for i in range(6)]
    buf = io.BytesIO()
    frames[0].save(buf, "GIF", save_all=True, append_images=frames[1:],
                   duration=100, loop=0)
    return buf.getvalue()


def _fillbyte_jpeg() -> bytes:
    pil = _pil()
    img = pil.new("RGB", (8, 8), (120, 200, 60))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=50)
    raw = buf.getvalue()
    sof = raw.find(b"\xff\xc0")
    return raw[:sof] + b"\xff" + raw[sof:]


# ═════════ 8. Делегирование живых путей ════════════════════════════════════


class TestDelegationParity:
    @pytest.mark.asyncio
    async def test_postgen_uses_adaptive_and_keeps_contract(self, vision_env):
        data = _jpeg((1200, 900), quality=97)
        t = OcrTransport([], [], fail_status=400, fail_first=1)
        outcome = await pv.analyze_generated_image(data, chat_id=CHAT,
                                                   transport=t)
        assert outcome.status in (pv.STATUS_READY, pv.STATUS_NO_TEXT)
        assert len(t.calls) == 2 and t.calls[1]["bytes"] < t.calls[0]["bytes"]

    def test_job_path_uses_adaptive(self):
        src = Path(mca_vision.__file__).read_text(encoding="utf-8")
        assert "await analyze_adaptive(" in src


# ═════════ 9. NF-1: прод-бэкенд без Pillow (ffmpeg) ════════════════════════


class TestProdBackendNoPillow:
    """NF-1 (ревью REV-VISION-ADAPT): на ffmpeg-бэкенде (Pillow отсутствует)
    PNG-путь падал ImportError и ломал контракт «никогда не бросает»; GIF
    «сплющивался». Фикстуры строятся ДО блокировки PIL."""

    @staticmethod
    def _block_pil(monkeypatch):
        monkeypatch.setitem(sys.modules, "PIL", None)
        inorm.reset_codec_cache()

    def test_long_png_never_raises(self, monkeypatch):
        data, _lines, _colors = _long_screenshot()      # фикстура до блокировки
        self._block_pil(monkeypatch)
        assert inorm.codec_available() == "ffmpeg"
        out = inorm.optimize_to_fit(data, limits=inorm.vision_limits())
        assert out is None or (len(out) < len(data)
                               and mca_vision.sniff_image(out) is not None)

    def test_opaque_png_still_optimized(self, monkeypatch):
        """Непрозрачный PNG на ffmpeg — JPEG-путь (копия меньше)."""
        data, _lines, _colors = _long_screenshot()
        self._block_pil(monkeypatch)
        out = inorm.optimize_to_fit(data, limits=inorm.vision_limits())
        if out is not None:
            mime, _w, _h = mca_vision.sniff_image(out)
            assert mime == "image/jpeg"

    def test_transparent_png_not_flattened(self, monkeypatch):
        data = _transparent_png()                       # фикстура до блокировки
        self._block_pil(monkeypatch)
        out = inorm.optimize_to_fit(data, limits=inorm.vision_limits())
        assert out is None                              # без JPEG-флаттенинга

    def test_animated_gif_not_flattened(self, monkeypatch):
        data = _animated_gif()                          # фикстура до блокировки
        self._block_pil(monkeypatch)
        out = inorm.optimize_to_fit(data, limits=inorm.vision_limits())
        assert out is None                              # анимацию не «сплющиваем»

    @pytest.mark.asyncio
    async def test_analyze_adaptive_no_crash(self, monkeypatch, vision_env):
        data, truth, colors = _long_screenshot()
        self._block_pil(monkeypatch)
        img = validate_image_bytes(data)
        t = OcrTransport(truth, colors)
        out = await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=t)
        assert out.status in ("ready", "no_text")       # job доходит
        assert len(t.calls) >= 1                        # запрос состоялся

    def test_invariant_never_raises_battery(self, monkeypatch):
        """Контракт «никогда не бросает»: батарея входов × оба бэкенда."""
        fixtures = [_long_screenshot()[0], _transparent_png(), _animated_gif(),
                    _tiff(), _fillbyte_jpeg(), b"", b"garbage" * 100,
                    _jpeg((64, 48))]
        for block in (False, True):
            if block:
                self._block_pil(monkeypatch)
            else:
                monkeypatch.undo()
                inorm.reset_codec_cache()
            for blob in fixtures:
                out = inorm.optimize_to_fit(blob, limits=inorm.vision_limits())
                assert out is None or isinstance(out, bytes)


# ═════════ 10. NF-2: 400 без признаков image-проблемы — без повтора ═════════


class TestRetryClassGate:
    """NF-2 (ревью): 400 повторяется ТОЛЬКО при подтверждённом классе
    проблемы изображения; bare-400/model_not_found/context — без повтора."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("message,expect_calls", [
        ("unknown parameter: foo", 1),
        ("model_not_found: no endpoints found", 1),
        ("maximum context length is 4096 tokens", 1),
    ])
    async def test_arbitrary_400_no_retry(self, vision_env, message,
                                          expect_calls):
        img = validate_image_bytes(_jpeg((800, 600), quality=70))
        t = OcrTransport([], [], fail_status=400, fail_first=99,
                         fail_message=message)
        with pytest.raises(VisionError):
            await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=t)
        assert len(t.calls) == expect_calls

    @pytest.mark.asyncio
    async def test_image_class_400_retries(self, vision_env):
        img = validate_image_bytes(_jpeg((800, 600), quality=70))
        t = OcrTransport([], [], fail_status=400, fail_first=1,
                         fail_message="image too large")
        out = await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=t)
        assert len(t.calls) == 2 and out.status in ("ready", "no_text")

    @pytest.mark.asyncio
    async def test_413_bare_retries(self, vision_env):
        img = validate_image_bytes(_jpeg((800, 600), quality=70))
        t = OcrTransport([], [], fail_status=413, fail_first=1,
                         fail_message="payload too large")
        out = await mca_vision.analyze_adaptive(img, chat_id=CHAT, transport=t)
        assert len(t.calls) == 2 and out.status in ("ready", "no_text")
