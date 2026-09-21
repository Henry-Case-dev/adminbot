"""Хотфикс-3 (round10.25, T-2483…T-2487, ADR-1025-7 D1) — саммари: обложка
и rich на fallback-пути.

Падают на старом коде: при фолбэке Stage-1 «Редактор» (невалидный handoff /
таймаут) прежний код выставлял ``cover_prompt=""`` → plain без обложки, а
таймаут Stage-1 вообще ронял саммари в UX «упал апи».
"""
import json
import logging
from unittest.mock import AsyncMock, MagicMock

import pytest

from config.settings import Settings
from services import summary_generator as sg
from services.llm_client import LLMTimeoutError
from services.summary_generator import SummaryGenerator, compose_cover_image_prompt
from services.summary_prompts import SUMMARY_COVER_STYLE_DEFAULT
from services.system2_handoff import parse_summary_handoff_ex
from services.telegram_send import SUMMARY_COVER_MEDIA_ID

pytestmark = pytest.mark.system2

_VALID_DIGEST = "# Тема\n- Вася спорил с Петей"


@pytest.fixture
def no_sleep(monkeypatch):
    """Как в test_summary_generator: срезаем retry-паузы _llm_generate."""
    import asyncio as real_asyncio

    fake = MagicMock()
    fake.sleep = AsyncMock(return_value=None)
    fake.Lock = real_asyncio.Lock
    monkeypatch.setattr(sg, "asyncio", fake)
    return fake.sleep


# Review L10.25H4-5: общие хелперы вынесены из тест-модуля в
# `tests/summary_cover_helpers.py` — hotfix3/hotfix4-гейты не зависят от
# приватных символов друг друга.
from tests.summary_cover_helpers import (  # noqa: E402
    Recorder as _Recorder,
    env as _env,
    generator as _generator,
)


# ── A. Разбор handoff с причиной ────────────────────────────────────────

class TestParseHandoffReason:
    @pytest.mark.parametrize("raw,reason", [
        ("", "empty"),
        ("   ", "empty"),
        (None, "empty"),
        ("# мусор fact:12", "invalid_digest"),
        ('{"digest": ""}', "invalid_digest"),
        ('{"fact": "fact:1"}', "invalid_json"),
    ])
    def test_failure_reasons(self, raw, reason):
        parsed, got = parse_summary_handoff_ex(raw)
        assert parsed is None
        assert got == reason

    def test_valid_json_reason_ok(self):
        raw = json.dumps({"response_mode": "casual", "digest": _VALID_DIGEST,
                          "cover_prompt": "neon cat"})
        parsed, reason = parse_summary_handoff_ex(raw)
        assert reason == "ok"
        assert parsed["cover_prompt"] == "neon cat"

    def test_legacy_digest_reason_ok(self):
        parsed, reason = parse_summary_handoff_ex(_VALID_DIGEST)
        assert reason == "ok"
        assert parsed["digest"] == _VALID_DIGEST


# ── B. Обложка/rich на fallback-пути (T-2485/T-2487) ────────────────────

class TestFallbackCoverDelivery:
    @pytest.mark.asyncio
    async def test_fallback_invalid_handoff_sends_rich_with_cover(
            self, monkeypatch, tmp_path, caplog):
        rec = _Recorder()
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpegbytes")
        _env(monkeypatch, rec, cover_path=str(img))
        # Stage-1 невалиден → одиночный путь отдаёт текст.
        gen, _llm = _generator(["# мусор fact:12", "одиночный дерзкий текст"])
        with caplog.at_level(logging.INFO, logger=sg.__name__):
            await gen._run(-100, False)

        assert rec.plain == []                    # plain не использовался
        assert len(rec.rich) == 1
        assert rec.rich[0]["cover_id"] == SUMMARY_COVER_MEDIA_ID
        assert rec.rich[0]["media"] and len(rec.rich[0]["media"]) == 1
        # Обложка реально запрошена (не потеряна) и стиль подмешан.
        assert rec.image_prompts
        assert rec.image_prompts[0].startswith(SUMMARY_COVER_STYLE_DEFAULT)
        assert "одиночный дерзкий текст" in rec.image_prompts[0]
        # R17-safe лог причины фолбэка (T-2483).
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "reason=invalid_digest" in joined
        assert "reason=stage1_fallback" in joined

    @pytest.mark.asyncio
    async def test_fallback_flag_off_is_plain(self, monkeypatch, tmp_path):
        rec = _Recorder()
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpegbytes")
        _env(monkeypatch, rec, cover_path=str(img))
        monkeypatch.setattr(Settings, "SUMMARY_COVER_FALLBACK_ENABLED", False)
        gen, _llm = _generator(["# мусор fact:12", "одиночный текст"])

        await gen._run(-100, False)

        assert rec.rich == []
        assert rec.image_prompts == []
        assert rec.plain and "одиночный текст" in rec.plain[0]

    @pytest.mark.asyncio
    async def test_fallback_rich_unsupported_logs_reason(
            self, monkeypatch, caplog):
        rec = _Recorder()
        _env(monkeypatch, rec, cover_path="ignored", rich=False)
        gen, _llm = _generator(["# мусор fact:12", "одиночный текст"])
        with caplog.at_level(logging.INFO, logger=sg.__name__):
            await gen._run(-100, False)

        assert rec.rich == []
        assert rec.plain
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "reason=rich_unsupported" in joined

    @pytest.mark.asyncio
    async def test_successful_rich_path_unchanged(
            self, monkeypatch, tmp_path):
        rec = _Recorder()
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpegbytes")
        _env(monkeypatch, rec, cover_path=str(img))
        editor = json.dumps({"response_mode": "casual",
                             "digest": _VALID_DIGEST,
                             "cover_prompt": "a lone cat"})
        gen, _llm = _generator([editor, "готовый текст"])

        await gen._run(-100, False)

        assert len(rec.rich) == 1
        # Успешный путь использует промпт Редактора, а не детерминированный.
        assert rec.image_prompts == [
            compose_cover_image_prompt(SUMMARY_COVER_STYLE_DEFAULT,
                                       "a lone cat")]

    @pytest.mark.asyncio
    async def test_stage1_timeout_falls_back_to_single_and_rich(
            self, monkeypatch, tmp_path, no_sleep, caplog):
        rec = _Recorder()
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpegbytes")
        _env(monkeypatch, rec, cover_path=str(img))
        # Stage-1: таймаут + retry-once (внутри _llm_generate) → фолбэк;
        # затем одиночный путь отдаёт текст.
        gen, _llm = _generator([
            LLMTimeoutError("stage1 timeout"),
            LLMTimeoutError("stage1 timeout retry"),
            "одиночный текст после таймаута",
        ])
        with caplog.at_level(logging.WARNING, logger=sg.__name__):
            await gen._run(-100, False)

        assert len(rec.rich) == 1              # обложка не потеряна
        assert rec.ux == []                    # нет UX «упал апи»
        joined = "\n".join(r.getMessage() for r in caplog.records)
        assert "reason=timeout" in joined


class TestSystem2OffBaseline:
    @pytest.mark.asyncio
    async def test_system2_off_single_path_is_plain(self, monkeypatch, tmp_path):
        """L-3: `SYSTEM2_SUMMARY_ENABLED=False` → одиночный путь без обложки
        (plain), cover-fallback НЕ включается (это конфиг, не фолбэк)."""
        rec = _Recorder()
        img = tmp_path / "cover.jpg"
        img.write_bytes(b"jpegbytes")
        _env(monkeypatch, rec, cover_path=str(img))
        monkeypatch.setattr(Settings, "SYSTEM2_SUMMARY_ENABLED", False)
        gen, _llm = _generator(["одиночный текст"])

        await gen._run(-100, False)

        assert rec.rich == []
        assert rec.image_prompts == []
        assert rec.plain and "одиночный текст" in rec.plain[0]
