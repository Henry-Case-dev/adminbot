# -*- coding: utf-8 -*-
"""POSTGEN-DIAG (19.10.2026) — диагностика и фикс класса отказов
`image_postgen_vision=failed/vision_failed` (прод 2.58.94, ACCEPTANCE-94) и
класса `vision_unreadable` на реальных фото (VISION_DL_STAGE=6).

Факты из прод-эвиденса (`plans/features/p0-vision-universal/evidence/
release-25894/acceptance/`):

  * b2-postgen.json: генерация 939495 B (qwen-image-3-pro) →
    `image_postgen_vision` failed/`vision_failed`; провайдер жив (b1:
    131641 B JPEG → ready, тот же chat/model 40 c раньше);
    `vision_transport_calls=2` в harness-процессе = 1 проба b1 + 1 вызов
    пост-генерации ⇒ вызов ДОШЁЛ до провайдера и получил non-2xx
    (не 401/403/429) — но статус/класс ответа МАСКИРОВАЛИСЬ (в
    outcome/событии только reason_code=vision_failed);
  * p0-pre-state/journal: джобы упали на stage=download с
    `vision_unreadable` БЕЗ класса причины (detail VisionError терялся);
  * локальная репродукция (repro.json): легальный JPEG с fill-байтами 0xFF
    (Pillow декодирует) наш сниффер отвергает → ложный `vision_unreadable`;
    TIFF (реальный формат документа-фото) — отвергается; 939 КБ JPEG проходит
    локальный гейт (значит, отказ прод-постгена — не наш валидатор).

Покрытие:
  * REGRESSION: fill-байты JPEG больше не «unreadable»;
  * CONTRACT: bounded декод-фоллбэк (TIFF/экзотика → нормализованный JPEG),
    fail-open/kill-switch;
  * REGRESSION: провайдер-ошибки не маскируются (detail http_<status>/класс);
  * CONTRACT: ровно один bounded retry с нормализованным payload на
    image-class отказ провайдера (400/413/415/422), не на 5xx/429/таймаут.

Без сети и без живых провайдеров (контрактные моки).

TEST-LIFECYCLE: REGRESSION owner=POSTGEN-DIAG
TEST-LIFECYCLE: CONTRACT owner=POSTGEN-DIAG
"""
from __future__ import annotations

import asyncio
import io
import json
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config.settings import Settings                        # noqa: E402
from services import mca_vision                             # noqa: E402
from services import postgen_vision as pv                   # noqa: E402
from services.mca_vision import VisionError                 # noqa: E402

CHAT = -1009001

PNG_1PX = bytes.fromhex(
    "89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c489"
    "0000000d4944415478da63fcffff3f0300050201cfa02d0d0000000049454e44ae"
    "426082")

#: Легальный JPEG 8×8 (Pillow-декодируемый) с fill-байтом 0xFF перед SOF0 —
#: спека JPEG допускает fill-байты; наш сниффер на нём падал (репродукция).
JPEG_FILLBYTE = bytes.fromhex(
    "ffd8ffe000104a46494600010100000100010000ffdb004300100b0c0e0c0a100e0d0e12"
    "11101318281a181616183123251d283a333d3c3933383740485c4e404457453738506d51"
    "575f626768673e4d71797064785c656763ffdb0043011112121815182f1a1a2f63423842"
    "636363636363636363636363636363636363636363636363636363636363636363636363"
    "6363636363636363636363636363ffffc00011080008000803012200021101031101ffc4"
    "001f0000010501010101010100000000000000000102030405060708090a0bffc400b510"
    "0002010303020403050504040000017d0102030004110512213141061351610722711432"
    "8191a1082342b1c11552d1f02433627282090a161718191a25262728292a343536373839"
    "3a434445464748494a535455565758595a636465666768696a737475767778797a838485"
    "868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3c4c5"
    "c6c7c8c9cad2d3d4d5d6d7d8d9dae1e2e3e4e5e6e7e8e9eaf1f2f3f4f5f6f7f8f9faffc4"
    "001f0100030101010101010101010000000000000102030405060708090a0bffc400b511"
    "000201020404030407050404000102770001020311040521310612415107617113223281"
    "08144291a1b1c109233352f0156272d10a162434e125f11718191a262728292a35363738"
    "393a434445464748494a535455565758595a636465666768696a737475767778797a8283"
    "8485868788898a92939495969798999aa2a3a4a5a6a7a8a9aab2b3b4b5b6b7b8b9bac2c3"
    "c4c5c6c7c8c9cad2d3d4d5d6d7d8d9dae2e3e4e5e6e7e8e9eaf2f3f4f5f6f7f8f9faffda"
    "000c03010002110311003f00d0a28a2bc4384fffd9")

#: TIFF 8×8 RGB (реальный формат документа-фото): Pillow читает, сниффер нет.
TIFF_BYTES = bytes.fromhex(
    "49492a00080000000a000001040001000000080000000101040001000000080000000201"
    "030003000000860000000301030001000000010000000601030001000000020000001101"
    "0400010000008c0000001501030001000000030000001601040001000000080000001701"
    "040001000000c00000001c01030001000000010000000000000008000800080078c83c78"
    "c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78"
    "c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78"
    "c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78"
    "c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78"
    "c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78c83c78"
    "c83c78c83c78c83c")


def _set_env(name: str, value, monkeypatch) -> None:
    for cls in {Settings, type(pv.settings)}:
        if hasattr(cls, name):
            monkeypatch.setattr(cls, name, value)


def _ok_body(desc: str = "жёлтый лимон на белом фоне") -> dict:
    return {"choices": [{"message": {"content": json.dumps(
        {"ocr_blocks": [], "visual_description": desc,
         "uncertainty": []}, ensure_ascii=False)}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 5}}


class _Transport:
    """Контрактный мок провайдера: очередь (status, body) или исключений."""

    def __init__(self, *results):
        self.results = list(results)
        self.calls: list[dict] = []

    async def __call__(self, url, *, payload=None, headers=None, timeout=None):
        img = payload["messages"][1]["content"][1]["image_url"]["url"]
        self.calls.append({"image_chars": len(img), "timeout": timeout})
        res = self.results.pop(0) if self.results else self.results_last
        self.results_last = res
        if isinstance(res, BaseException):
            raise res
        return res


async def _state_ok(chat_id=None):
    return SimpleNamespace(effective_enabled=True, capability="ok",
                           reason="vision_ok", visible_reason="ok")


@pytest.fixture()
def postgen_env(monkeypatch):
    """Vision-capable состояние + маршрут без конфиг-проблем + чистый кеш
    пост-гена (без сети: транспорт — контрактный мок)."""
    monkeypatch.setattr(mca_vision, "resolve_effective_state", _state_ok)
    monkeypatch.setattr(mca_vision, "route_config_problem", lambda route: "")
    monkeypatch.setattr(mca_vision, "api_key_for", lambda route: "test-key")
    pv.reset_cache()
    yield
    pv.reset_cache()


@pytest.fixture()
def vision_route_ok(monkeypatch):
    """Маршрут валиден (иначе analyze_image_bytes падает до транспорта)."""
    monkeypatch.setattr(mca_vision, "route_config_problem", lambda route: "")
    monkeypatch.setattr(mca_vision, "api_key_for", lambda route: "test-key")


# ═════════════ REGRESSION: легальный JPEG с fill-байтами «unreadable» ══════


class TestSniffFalseNegative:
    def test_plain_jpeg_readable(self):
        plain = JPEG_FILLBYTE.replace(b"\xff\xff\xc0", b"\xff\xc0", 1)
        sniffed = mca_vision.sniff_image(plain)
        assert sniffed is not None
        assert sniffed[0] == "image/jpeg" and sniffed[1:] == (8, 8)

    def test_fillbyte_jpeg_readable(self):
        """0xFF-fill перед SOF (легально, Pillow декодирует) — не unreadable."""
        sniffed = mca_vision.sniff_image(JPEG_FILLBYTE)
        assert sniffed is not None, "fill-байт JPEG отвергнут сниффером"
        mime, width, height = sniffed
        assert mime == "image/jpeg" and (width, height) == (8, 8)
        img = mca_vision.validate_image_bytes(JPEG_FILLBYTE)
        assert img.mime == "image/jpeg" and img.byte_size == len(JPEG_FILLBYTE)

    def test_multiple_fill_bytes_readable(self):
        sof = JPEG_FILLBYTE.find(b"\xff\xc0")
        data = JPEG_FILLBYTE[:sof] + b"\xff\xff\xff" + JPEG_FILLBYTE[sof:]
        assert mca_vision.sniff_image(data) == ("image/jpeg", 8, 8)


# ═════════════ CONTRACT: bounded нормализация (декод-фоллбэк) ═══════════════


class TestNormalizerContract:
    def test_codec_detection_and_fail_open(self):
        from services import image_normalize as inorm
        assert inorm.codec_available() in ("pillow", "ffmpeg", "")
        assert inorm.normalize_jpeg_bytes(b"") is None
        assert inorm.normalize_jpeg_bytes(b"not-an-image" * 10) is None

    def test_disabled_kill_switch(self, monkeypatch):
        from services import image_normalize as inorm
        _set_env("MCA_VISION_NORMALIZE_ENABLED", False, monkeypatch)
        assert inorm.normalize_enabled() is False
        assert inorm.normalize_jpeg_bytes(JPEG_FILLBYTE) is None

    @pytest.mark.skipif(
        __import__("shutil").which("ffmpeg") is None
        and __import__("importlib").util.find_spec("PIL") is None,
        reason="нет локального кодека (Pillow/ffmpeg)")
    def test_real_codec_downscales_and_reencodes(self):
        """Реальный кодек: большая картинка → JPEG ≤ max_dimension и меньше."""
        from services import image_normalize as inorm
        pil = pytest.importorskip("PIL.Image")
        img = pil.new("RGB", (1600, 1200), (10, 120, 240))
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=95)
        raw = buf.getvalue()
        out = inorm.normalize_jpeg_bytes(raw, max_dimension=640)
        assert out is not None and len(out) < len(raw)
        mime, w, h = mca_vision.sniff_image(out)
        assert mime == "image/jpeg"
        assert max(w, h) <= 640

    def test_never_raises_on_garbage(self, monkeypatch):
        from services import image_normalize as inorm
        for blob in (b"\x00" * 5, b"\xff\xd8" + b"x" * 100, TIFF_BYTES[:20]):
            assert inorm.normalize_jpeg_bytes(blob) is None

    @pytest.mark.skipif(
        __import__("shutil").which("ffmpeg") is None,
        reason="ffmpeg недоступен локально")
    def test_ffmpeg_backend_when_pillow_absent(self, monkeypatch):
        """Прод-вероятный кодек: Pillow нет, ffmpeg есть → тот же контракт."""
        from services import image_normalize as inorm
        monkeypatch.setattr(inorm, "_pillow_available", lambda: False)
        inorm.reset_codec_cache()
        try:
            assert inorm.codec_available() == "ffmpeg"
            out = inorm.normalize_jpeg_bytes(JPEG_FILLBYTE, max_dimension=8)
            assert out is not None and out.startswith(b"\xff\xd8")
            assert mca_vision.sniff_image(out) == ("image/jpeg", 8, 8)
        finally:
            inorm.reset_codec_cache()

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        __import__("shutil").which("ffmpeg") is None,
        reason="ffmpeg недоступен локально")
    async def test_ffmpeg_backend_rescues_tiff(self, monkeypatch):
        from services import image_normalize as inorm
        monkeypatch.setattr(inorm, "_pillow_available", lambda: False)
        inorm.reset_codec_cache()
        try:
            img = await mca_vision.validate_or_normalize(TIFF_BYTES)
            assert img.mime == "image/jpeg"
            assert (img.width, img.height) == (8, 8)
        finally:
            inorm.reset_codec_cache()


# ═════════════ CONTRACT: validate_or_normalize (fallback входа) ═════════════


class TestValidateOrNormalize:
    @pytest.mark.asyncio
    async def test_valid_image_untouched(self):
        """Байт-в-байт: обычный валидный вход не нормализуется (паритет)."""
        img = await mca_vision.validate_or_normalize(PNG_1PX)
        assert img.data == PNG_1PX and img.mime == "image/png"

    @pytest.mark.asyncio
    async def test_tiff_rescued_via_normalization(self):
        """TIFF (Pillow/ffmpeg-декодируемый) → нормализованный JPEG."""
        from services import image_normalize as inorm
        if not inorm.codec_available():
            pytest.skip("нет локального кодека")
        img = await mca_vision.validate_or_normalize(TIFF_BYTES)
        assert img.mime == "image/jpeg"
        assert (img.width, img.height) == (8, 8)
        assert mca_vision.sniff_image(img.data) is not None

    @pytest.mark.asyncio
    async def test_no_codec_keeps_original_detail(self, monkeypatch):
        from services import image_normalize as inorm
        monkeypatch.setattr(inorm, "codec_available", lambda: "")
        with pytest.raises(VisionError) as ei:
            await mca_vision.validate_or_normalize(TIFF_BYTES)
        assert ei.value.reason == "vision_unreadable"
        assert ei.value.detail == "not a supported raster image"

    @pytest.mark.asyncio
    async def test_kill_switch_off_keeps_original(self, monkeypatch):
        _set_env("MCA_VISION_NORMALIZE_ENABLED", False, monkeypatch)
        with pytest.raises(VisionError) as ei:
            await mca_vision.validate_or_normalize(TIFF_BYTES)
        assert ei.value.reason == "vision_unreadable"

    @pytest.mark.asyncio
    async def test_download_telegram_file_uses_fallback(self, monkeypatch):
        from services import image_normalize as inorm
        if not inorm.codec_available():
            pytest.skip("нет локального кодека")

        class _File:
            file_path = "x"

        class _Bot:
            async def get_file(self, file_id):
                return _File()

            async def download(self, tg_file, destination):
                destination.write(TIFF_BYTES)

        img = await mca_vision.download_telegram_file(_Bot(), "fid")
        assert img.mime == "image/jpeg" and img.byte_size > 0


# ═════════════ REGRESSION: провайдер-ошибки не маскируются ═════════════════


class TestProviderErrorDetail:
    @pytest.mark.asyncio
    async def test_analyze_error_detail_carries_status_and_class(
            self, vision_route_ok):
        t = _Transport((400, {"error": {"message": "image too large",
                                        "code": "invalid_request"}}))
        img = mca_vision.validate_image_bytes(JPEG_FILLBYTE)
        with pytest.raises(VisionError) as ei:
            await mca_vision.analyze_image_bytes(img, chat_id=CHAT,
                                                 transport=t)
        assert ei.value.reason == "vision_failed"
        assert ei.value.detail.startswith("http_400")
        assert "image_rejected" in ei.value.detail

    @pytest.mark.asyncio
    async def test_analyze_error_detail_plain_status_when_no_body(
            self, vision_route_ok):
        t = _Transport((404, {}))
        img = mca_vision.validate_image_bytes(JPEG_FILLBYTE)
        with pytest.raises(VisionError) as ei:
            await mca_vision.analyze_image_bytes(img, chat_id=CHAT,
                                                 transport=t)
        assert ei.value.detail.startswith("http_404")

    @pytest.mark.asyncio
    async def test_postgen_outcome_detail_on_provider_400(self, postgen_env,
                                                          monkeypatch):
        from services import image_normalize as inorm
        monkeypatch.setattr(inorm, "normalize_jpeg_bytes_async",
                            _none_async)
        t = _Transport((400, {"error": {"message": "image too large"}}))
        outcome = await pv.analyze_generated_image(
            JPEG_FILLBYTE, chat_id=CHAT, transport=t)
        assert outcome.status == pv.STATUS_FAILED
        assert outcome.reason == "vision_failed"
        assert outcome.detail.startswith("http_400")
        assert len(t.calls) == 1                     # retry не выигрывает

    @pytest.mark.asyncio
    async def test_postgen_outcome_detail_on_generic_exception(self,
                                                               postgen_env,
                                                               monkeypatch):
        async def _boom(*a, **kw):
            raise RuntimeError("boom")

        monkeypatch.setattr(mca_vision, "analyze_image_bytes", _boom)
        outcome = await pv.analyze_generated_image(
            JPEG_FILLBYTE, chat_id=CHAT)
        assert outcome.status == pv.STATUS_FAILED
        assert outcome.detail == "RuntimeError"

    @pytest.mark.asyncio
    async def test_postgen_event_carries_detail(self, postgen_env,
                                                monkeypatch):
        captured: list[dict] = []

        def _emit(name, **fields):
            captured.append({"name": name, **fields})

        monkeypatch.setattr(mca_vision, "resolve_effective_state", _state_ok)
        from services import mca_events
        monkeypatch.setattr(mca_events, "emit_mca_event", _emit)
        t = _Transport((500, {}))
        await pv.analyze_generated_image(JPEG_FILLBYTE, chat_id=CHAT,
                                         transport=t)
        post = [c for c in captured if c["name"] == "image_postgen_vision"]
        assert post and post[-1]["error_json"]["detail"].startswith("http_500")

    @pytest.mark.asyncio
    async def test_job_stage_event_carries_unreadable_detail(self,
                                                             monkeypatch):
        captured: list[dict] = []

        def _emit(name, **fields):
            captured.append({"name": name, **fields})

        from services import mca_events
        monkeypatch.setattr(mca_events, "emit_mca_event", _emit)

        async def _finish(status, reason, result_ref=None):
            return None

        class _Db:
            async def finish_media_analysis(self, *a, **kw):
                return None

        await mca_vision._finish_analysis_or_job(
            _Db(), 0, 0, {"job_id": None, "attempt": 0}, _finish,
            "vision_unreadable", "unreadable", chat_id=CHAT,
            asset_id="a1", stage="download",
            detail="not a supported raster image")
        stages = [c for c in captured if c["name"] == "vision_media"]
        assert stages and stages[-1]["error_json"]["detail"] == \
            "not a supported raster image"


async def _none_async(*a, **kw):
    return None


# ═════════════ CONTRACT: один bounded retry с нормализацией ════════════════


class TestRetryWithNormalizedPayload:
    @pytest.mark.asyncio
    async def test_retry_on_image_class_400_succeeds(self, postgen_env,
                                                     monkeypatch):
        """400 (image-class) → ОДИН retry с меньшим payload → ready."""
        from services import image_normalize as inorm

        async def _normalize(data, *, max_dimension=None):
            return JPEG_FILLBYTE                      # меньше исходного

        monkeypatch.setattr(inorm, "normalize_jpeg_bytes_async", _normalize)
        big = PNG_1PX + b"\x00" * 4096                # «большой» исходник
        t = _Transport((400, {"error": {"message": "image too large"}}),
                       (200, _ok_body()))
        outcome = await pv.analyze_generated_image(big, chat_id=CHAT,
                                                   transport=t)
        assert outcome.status == pv.STATUS_READY
        assert len(t.calls) == 2
        assert t.calls[1]["image_chars"] < t.calls[0]["image_chars"]

    @pytest.mark.asyncio
    async def test_no_retry_on_5xx(self, postgen_env, monkeypatch):
        from services import image_normalize as inorm
        calls = {"n": 0}

        async def _normalize(data, *, max_dimension=None):
            calls["n"] += 1
            return JPEG_FILLBYTE

        monkeypatch.setattr(inorm, "normalize_jpeg_bytes_async", _normalize)
        t = _Transport((500, {}))
        outcome = await pv.analyze_generated_image(PNG_1PX, chat_id=CHAT,
                                                   transport=t)
        assert outcome.status == pv.STATUS_FAILED
        assert len(t.calls) == 1 and calls["n"] == 0

    @pytest.mark.asyncio
    async def test_no_retry_on_429(self, postgen_env, monkeypatch):
        t = _Transport((429, {}))
        outcome = await pv.analyze_generated_image(PNG_1PX, chat_id=CHAT,
                                                   transport=t)
        assert outcome.status == pv.STATUS_RATE_LIMITED
        assert len(t.calls) == 1

    @pytest.mark.asyncio
    async def test_retry_failure_keeps_honest_detail(self, postgen_env,
                                                     monkeypatch):
        from services import image_normalize as inorm

        async def _normalize(data, *, max_dimension=None):
            return JPEG_FILLBYTE

        monkeypatch.setattr(inorm, "normalize_jpeg_bytes_async", _normalize)
        big = PNG_1PX + b"\x00" * 4096
        t = _Transport((400, {"error": {"message": "image too large"}}),
                       (400, {"error": {"message": "image too large"}}))
        outcome = await pv.analyze_generated_image(big, chat_id=CHAT,
                                                   transport=t)
        assert outcome.status == pv.STATUS_FAILED
        assert outcome.detail.startswith("http_400")
        assert len(t.calls) == 2

    @pytest.mark.asyncio
    async def test_no_retry_when_no_remaining_budget(self, postgen_env,
                                                     monkeypatch):
        from services import image_normalize as inorm

        async def _normalize(data, *, max_dimension=None):
            return JPEG_FILLBYTE

        monkeypatch.setattr(inorm, "normalize_jpeg_bytes_async", _normalize)
        monkeypatch.setattr(pv, "analysis_budget_seconds", lambda: 0.05)
        t = _Transport((400, {"error": {"message": "image too large"}}))
        outcome = await pv.analyze_generated_image(PNG_1PX + b"\x00" * 64,
                                                   chat_id=CHAT, transport=t)
        assert outcome.status == pv.STATUS_FAILED
        assert len(t.calls) == 1

    @pytest.mark.asyncio
    async def test_retry_skipped_when_normalize_disabled(self, postgen_env,
                                                         monkeypatch):
        _set_env("MCA_VISION_NORMALIZE_ENABLED", False, monkeypatch)
        t = _Transport((400, {"error": {"message": "image too large"}}))
        outcome = await pv.analyze_generated_image(PNG_1PX + b"\x00" * 64,
                                                   chat_id=CHAT, transport=t)
        assert outcome.status == pv.STATUS_FAILED
        assert len(t.calls) == 1


# ═════════════ CONTRACT: постген-лог видим в journal-фильтрах ══════════════


class TestLogVisibility:
    @pytest.mark.asyncio
    async def test_postgen_log_prefix_is_vision_family(self, postgen_env,
                                                       monkeypatch, caplog):
        """Прод-эвиденс фильтрует по «[vision]»: строка пост-гена должна
        попадать в семейство (иначе диагностика теряется, как в ACCEPTANCE-94)."""
        import logging
        t = _Transport((200, _ok_body()))
        with caplog.at_level(logging.INFO, logger="services.postgen_vision"):
            await pv.analyze_generated_image(JPEG_FILLBYTE, chat_id=CHAT,
                                             transport=t)
        text = "\n".join(r.getMessage() for r in caplog.records)
        assert "[vision]" in text and "postgen" in text
