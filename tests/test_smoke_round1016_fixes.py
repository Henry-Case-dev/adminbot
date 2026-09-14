"""Смоук/регресс раунда 10.16 (T-1649) — закрытый Low-техдолг.

Регресс-тесты по FIX-пунктам spec §3/§5:
  * S10.13-6b: `graph_stats.archived_beliefs` исключает F3-парадигмы;
  * S10.13-13: единый `parse_belief_meta` (database) и его делегаты;
  * R10.15-4: router 4e всегда зарегистрирован + горячий гейт в хендлере +
    yield direct_chat только при доступном сервисе;
  * R10.15-10: link-first по вхождению имени с URL перед ним;
  * R10.15-11: youtube не консьюмит не-media URL, но берёт валидную цель.
"""
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiogram.dispatcher.event.bases import UNHANDLED

from handlers import direct_chat as dc
from handlers import video_download as vd
from handlers import web as web_mod
from handlers import youtube as youtube_mod
from services import bot_persona
from services import command_prefix as cp
from services.database import DatabaseService, parse_belief_meta
from services.dream_worker import DreamWorker
from services.summary_memory import _belief_base_weight

ROOT = Path(".")
YT_URL = "https://youtu.be/dQw4w9WgXcQ"
WEB_URL = "https://habr.com/ru/articles/1"
CHAT_ID = -1001234567890


def _read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


# ── S10.13-6b ────────────────────────────────────────────────────────────


class TestArchivedBeliefsParadigmFilter:
    @pytest.mark.asyncio
    async def test_paradigms_excluded_from_archived_count(self):
        db = DatabaseService(":memory:")
        await db.initialize()
        try:
            await db.insert_graph_fact(
                CHAT_ID, "обычное архивное", "derived_belief", None,
                status="archived_belief", kind="belief")
            await db.insert_graph_fact(
                CHAT_ID, "архивная парадигма", "derived_belief", None,
                status="archived_belief", kind="belief",
                belief_meta=json.dumps({"type": "paradigm"}))
            stats = await db.graph_stats(CHAT_ID)
            assert stats["archived_beliefs"] == 1
            assert stats["paradigms"] == 1
        finally:
            await db.close()


# ── S10.13-13 ────────────────────────────────────────────────────────────


class TestUnifiedBeliefMetaParser:
    def test_parse_variants(self):
        assert parse_belief_meta('{"base_weight": 0.7}') == {"base_weight": 0.7}
        assert parse_belief_meta({"x": 1}) == {"x": 1}
        assert parse_belief_meta(None) == {}
        assert parse_belief_meta("") == {}
        assert parse_belief_meta("{broken") == {}
        assert parse_belief_meta("[1,2]") == {}

    def test_dream_worker_delegates(self):
        assert DreamWorker._belief_meta(
            {"belief_meta": '{"base_weight": 0.4}'}) == {"base_weight": 0.4}
        assert DreamWorker._belief_meta({"belief_meta": None}) == {}

    def test_summary_memory_delegates(self):
        assert _belief_base_weight(
            {"belief_meta": '{"base_weight": 0.9}'}) == 0.9
        assert _belief_base_weight({"belief_meta": "{broken"}) == 0.6
        assert _belief_base_weight({}) == 0.6


# ── R10.15-4 ─────────────────────────────────────────────────────────────


class TestDownloadAlwaysRegistered:
    def test_bot_registers_router_unconditionally(self):
        src = _read("bot.py")
        assert "dp.include_router(video_download_router)" in src
        assert "registered (hot-gated" in src
        # стартовый гейт регистрации снят: include не под if hot.get
        idx = src.index("dp.include_router(video_download_router)")
        window = src[max(0, idx - 400):idx]
        assert "if hot.get(\"flags.download_enabled\"" not in window

    def test_handler_has_hot_gate(self):
        src = _read("handlers/video_download.py")
        assert 'hot.get("flags.download_enabled"' in src
        assert "def download_available()" in src

    @pytest.fixture
    def dc_env(self):
        old = (dc._service, dc._bot_id, dc._bot_username)
        dc.setup_direct_chat(service=MagicMock(), bot_id=999,
                             bot_username="adminbot")
        yield
        dc._service, dc._bot_id, dc._bot_username = old

    def _flag_on(self, monkeypatch):
        real_get = dc.hot.get
        monkeypatch.setattr(
            dc.hot, "get",
            lambda key, default=None: True
            if key == "flags.download_enabled" else real_get(key, default))

    @pytest.mark.asyncio
    async def test_no_service_yield_disabled_not_lost(self, dc_env,
                                                      monkeypatch):
        self._flag_on(monkeypatch)
        bot_persona.set_global_name_cache("Олег")
        monkeypatch.setattr(vd, "_downloader", None)
        dc._service.handle = AsyncMock()
        msg = MagicMock()
        msg.text = f"Олег, скачай {YT_URL}"
        msg.caption = None
        msg.chat = MagicMock()
        msg.chat.id = CHAT_ID
        msg.from_user = MagicMock()
        msg.from_user.id = 1
        monkeypatch.setattr(dc, "_is_direct_trigger", lambda m: True)
        result = await dc.direct_chat_handler(msg, bot=AsyncMock())
        assert result is not UNHANDLED
        dc._service.handle.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_service_available_yields(self, dc_env, monkeypatch):
        self._flag_on(monkeypatch)
        bot_persona.set_global_name_cache("Олег")
        monkeypatch.setattr(vd, "_downloader", MagicMock(busy=False))
        msg = MagicMock()
        msg.text = f"Олег, скачай {YT_URL}"
        msg.caption = None
        msg.chat = MagicMock()
        msg.chat.id = CHAT_ID
        msg.from_user = MagicMock()
        msg.from_user.id = 1
        monkeypatch.setattr(dc, "_is_direct_trigger", lambda m: True)
        result = await dc.direct_chat_handler(msg, bot=AsyncMock())
        assert result is UNHANDLED


# ── R10.15-10 ────────────────────────────────────────────────────────────


class TestLinkFirstOccurrence:
    @pytest.fixture
    def oleg_name(self):
        bot_persona.set_global_name_cache("Олег")
        yield

    def _msg(self, text):
        m = MagicMock()
        m.text = text
        m.caption = None
        m.message_id = 1
        m.chat = MagicMock()
        m.chat.id = CHAT_ID
        m.from_user = MagicMock()
        m.from_user.id = 1
        m.reply_to_message = None
        m.video = None
        m.document = None
        m.voice = None
        m.video_note = None
        return m

    def test_second_occurrence_after_url_chosen(self, oleg_name):
        text = f"эй Олег, смотри {YT_URL} Олег, поясни за видос"
        body = youtube_mod._triggered_body(self._msg(text))
        assert body is not None
        target, video_id = youtube_mod._parse(self._msg(text))
        assert video_id == "dQw4w9WgXcQ"

    def test_no_url_before_any_occurrence_is_none(self, oleg_name):
        text = "эй Олег, поясни за видос"
        assert youtube_mod._triggered_body(self._msg(text)) is None

    def test_web_second_occurrence_after_url(self, oleg_name):
        text = f"эй Олег, глянь {WEB_URL} Олег, выжимка"
        assert web_mod._triggered_body(self._msg(text)) is not None


# ── R10.15-11 ────────────────────────────────────────────────────────────


class TestValidVideoTargetOnly:
    @pytest.fixture
    def oleg_name(self):
        bot_persona.set_global_name_cache("Олег")
        yield

    def _msg(self, text):
        m = MagicMock()
        m.text = text
        m.caption = None
        m.message_id = 1
        m.chat = MagicMock()
        m.chat.id = CHAT_ID
        m.from_user = MagicMock()
        m.from_user.id = 1
        m.reply_to_message = None
        m.video = None
        m.document = None
        m.voice = None
        m.video_note = None
        return m

    def test_non_media_url_with_trigger_not_consumed(self, oleg_name):
        m = self._msg("Олег, глянь https://habr.com/x — там транскрипт обсуждают")
        assert youtube_mod._triggered_body(m) is None

    def test_youtube_target_consumed(self, oleg_name):
        m = self._msg(f"Олег, глянь {YT_URL} — там транскрипт обсуждают")
        assert youtube_mod._triggered_body(m) is not None

    def test_direct_media_target_consumed(self, oleg_name):
        m = self._msg("Олег, скинь https://cdn.example.com/v.mp4 транскрипт")
        assert youtube_mod._triggered_body(m) is not None

    def test_web_ignores_youtube_url(self, oleg_name):
        m = self._msg(f"Олег, выжимка {YT_URL}")
        # YouTube-URL не является целью web (D128): _parse не находит цель.
        target, url = web_mod._parse(m)
        assert target is None and url is None
