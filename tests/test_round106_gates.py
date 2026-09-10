"""Раунд 10.6 (INFO/ревью) — async-гейты 5 master-флагов модулей.

Flag OFF → handler возвращает UNHANDLED (прежняя пропагация), не отвечая.
"""
import types

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED
from unittest.mock import AsyncMock, MagicMock

from handlers import checkup as ck
from handlers import factcheck as fc
from handlers import search as sr
from handlers import web as wb
from handlers import youtube as yt


def _flag_off(monkeypatch, module):
    monkeypatch.setattr(module.hot, "get",
                        lambda key, default=None: False)


def _msg(text=""):
    m = MagicMock()
    m.text = text
    m.caption = None
    m.message_id = 1
    m.chat = MagicMock()
    m.chat.id = -1001
    m.from_user = MagicMock()
    m.from_user.id = 1
    m.reply_to_message = None
    m.forward_origin = None
    m.media_group_id = None
    return m


@pytest.mark.asyncio
async def test_factcheck_off_unhandled(monkeypatch):
    fc._service = MagicMock()
    _flag_off(monkeypatch, fc)
    try:
        res = await fc.factcheck_handler(_msg("фактчек https://x"),
                                         bot=AsyncMock())
        assert res is UNHANDLED
    finally:
        fc._service = None


@pytest.mark.asyncio
async def test_search_off_unhandled(monkeypatch):
    sr._service = MagicMock()
    _flag_off(monkeypatch, sr)
    try:
        res = await sr.smartsearch_handler(_msg("найди что-нибудь"),
                                           bot=AsyncMock())
        assert res is UNHANDLED
    finally:
        sr._service = None


@pytest.mark.asyncio
async def test_web_off_unhandled(monkeypatch):
    wb._service = MagicMock()
    _flag_off(monkeypatch, wb)
    try:
        res = await wb.web_handler(_msg("перескажи https://example.com"),
                                   bot=AsyncMock())
        assert res is UNHANDLED
    finally:
        wb._service = None


@pytest.mark.asyncio
async def test_checkup_off_unhandled(monkeypatch):
    ck._service = MagicMock()
    ck._fetcher = MagicMock()
    _flag_off(monkeypatch, ck)
    try:
        res = await ck.checkup_handler(_msg("чекап"), bot=AsyncMock())
        assert res is UNHANDLED
    finally:
        ck._service = None
        ck._fetcher = None


@pytest.mark.asyncio
async def test_youtube_summary_off_unhandled(monkeypatch):
    yt._service = MagicMock()
    _flag_off(monkeypatch, yt)
    monkeypatch.setattr(yt, "_classify_video_request",
                        lambda message: types.SimpleNamespace(mode="summary"))
    try:
        res = await yt.youtube_handler(_msg("перескажи видео"),
                                       bot=AsyncMock())
        assert res is UNHANDLED
    finally:
        yt._service = None


def test_flags_default_on():
    """ON (default) — поведение не меняется (проверяется значением Settings)."""
    from config.settings import Settings
    s = Settings()
    for field in ("FACTCHECK_ENABLED", "SEARCH_ENABLED",
                  "VIDEO_SUMMARY_ENABLED", "WEBPAGE_ENABLED",
                  "CHECKUP_ENABLED"):
        assert getattr(s, field) is True, field
