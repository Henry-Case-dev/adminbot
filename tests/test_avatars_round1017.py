"""F5 round 10.17 — гигиена логов `web/api/avatars.py` + brotli-WONTFIX.

Политика (spec.md §3):
  * `TelegramBadRequest` (ожидаемо: нет фото/прав/чата) → `DEBUG` БЕЗ
    `exc_info`; негатив кэшируется вызывающим кодом;
  * транзиент (`TelegramRetryAfter`/`TelegramNetworkError`) → `WARNING` БЕЗ
    трейса, негатив НЕ кэшируется (BUG-4, ветки не тронуты);
  * прочее (неожидаемо) → `WARNING` С `exc_info` (R17-safe).

Плюс brotli-док: `brotli` — build-time only (`scripts/requirements-font.txt`),
в runtime `requirements.txt` нет; Caddy-бротли — WONTFIX (zstd+gzip достаточно).
"""
import logging

import pytest


# ── вспомогательные заглушки Bot API ───────────────────────────────────────

def _records(caplog):
    return [r for r in caplog.records if r.name == "web.api.avatars"]


def _clear_caches():
    from web.api import avatars
    for cache in (avatars._avatar_cache, avatars._chat_info_cache,
                  avatars._username_cache, avatars._user_photo_cache,
                  avatars._user_name_cache):
        cache.clear()


@pytest.fixture(autouse=True)
def _isolate_caches():
    _clear_caches()
    yield
    _clear_caches()


# ═══ 1-3: ожидаемые TelegramBadRequest → DEBUG без трейса, негатив в кэш ════

class TestExpectedBadRequestIsQuiet:
    @pytest.mark.asyncio
    async def test_fetch_avatar_bytes_debug_without_traceback(
            self, caplog, monkeypatch):
        from aiogram.exceptions import TelegramBadRequest

        from web.api import avatars

        class FakeBot:
            async def get_chat(self, tid):
                raise TelegramBadRequest(method="getChat",
                                         message="chat not found")

        monkeypatch.setattr(avatars.web_runtime, "get_web_bot",
                            lambda: FakeBot())
        with caplog.at_level(logging.DEBUG, logger="web.api.avatars"):
            data = await avatars.fetch_avatar_bytes("chat", 42)

        assert data is None
        recs = _records(caplog)
        assert recs, "ожидалась запись в лог об ожидаемом сбое"
        assert all(r.levelno == logging.DEBUG for r in recs)
        assert all(r.exc_info is None for r in recs), "след не должен быть"
        assert ("chat", 42) in avatars._avatar_cache, "негатив кэшируется"
        assert avatars._avatar_cache[("chat", 42)][1] is None

    @pytest.mark.asyncio
    async def test_chat_display_info_debug_without_traceback(
            self, caplog, monkeypatch):
        from aiogram.exceptions import TelegramBadRequest

        from web.api import avatars

        class FakeBot:
            async def get_chat(self, chat_id):
                raise TelegramBadRequest(method="getChat",
                                         message="chat not found")

        monkeypatch.setattr(avatars.web_runtime, "get_web_bot",
                            lambda: FakeBot())
        with caplog.at_level(logging.DEBUG, logger="web.api.avatars"):
            info = await avatars.chat_display_info(42)

        assert info == {"title": None, "photo_file_id": None}
        recs = _records(caplog)
        assert recs and all(r.levelno == logging.DEBUG for r in recs)
        assert all(r.exc_info is None for r in recs)
        assert 42 in avatars._chat_info_cache, "негатив обогащения кэшируется"

    @pytest.mark.asyncio
    async def test_user_display_info_debug_without_traceback(
            self, caplog, monkeypatch):
        from aiogram.exceptions import TelegramBadRequest

        from web.api import avatars

        class FakeBot:
            async def get_chat_member(self, chat_id, user_id):
                raise TelegramBadRequest(method="getChatMember",
                                         message="user not found")

            async def get_user_profile_photos(self, user_id, limit=1):
                raise TelegramBadRequest(method="getUserProfilePhotos",
                                         message="photos not found")

        monkeypatch.setattr(avatars.web_runtime, "get_web_bot",
                            lambda: FakeBot())
        with caplog.at_level(logging.DEBUG, logger="web.api.avatars"):
            info = await avatars.user_display_info(42, 777)

        assert info == {"username": None, "photo_file_id": None}
        recs = _records(caplog)
        assert len(recs) >= 2, "два ожидаемых сбоя (member + photos)"
        assert all(r.levelno == logging.DEBUG for r in recs)
        assert all(r.exc_info is None for r in recs)
        assert (42, 777) in avatars._username_cache
        assert 777 in avatars._user_photo_cache

    @pytest.mark.asyncio
    async def test_global_user_display_info_debug_without_traceback(
            self, caplog, monkeypatch):
        from aiogram.exceptions import TelegramBadRequest

        from web.api import avatars

        class FakeBot:
            async def get_chat(self, user_id):
                raise TelegramBadRequest(method="getChat",
                                         message="user not found")

            async def get_user_profile_photos(self, user_id, limit=1):
                raise TelegramBadRequest(method="getUserProfilePhotos",
                                         message="photos not found")

        monkeypatch.setattr(avatars.web_runtime, "get_web_bot",
                            lambda: FakeBot())
        with caplog.at_level(logging.DEBUG, logger="web.api.avatars"):
            info = await avatars.global_user_display_info(999)

        assert info == {"display_name": None, "photo_file_id": None}
        recs = _records(caplog)
        assert len(recs) >= 2
        assert all(r.levelno == logging.DEBUG for r in recs)
        assert all(r.exc_info is None for r in recs)


# ═══ 4: неожидаемое → WARNING С трейсом (R17-safe) ═════════════════════════

class TestUnexpectedIsWarningWithTrace:
    @pytest.mark.asyncio
    async def test_fetch_runtime_error_warning_with_exc_info(
            self, caplog, monkeypatch):
        from web.api import avatars

        class FakeBot:
            async def get_chat(self, tid):
                raise RuntimeError("boom")

        monkeypatch.setattr(avatars.web_runtime, "get_web_bot",
                            lambda: FakeBot())
        with caplog.at_level(logging.WARNING, logger="web.api.avatars"):
            data = await avatars.fetch_avatar_bytes("chat", 55)

        assert data is None
        recs = _records(caplog)
        assert any(r.levelno == logging.WARNING and r.exc_info
                   for r in recs), "неожидаемое должно логироваться с трейсом"
        assert ("chat", 55) in avatars._avatar_cache, "негатив кэшируется"


# ═══ 5: транзиент → WARNING без трейса, НЕ кэшируется (BUG-4) ══════════════

class TestTransientNotCached:
    @pytest.mark.asyncio
    async def test_fetch_retry_after_warning_without_trace(
            self, caplog, monkeypatch):
        from aiogram.exceptions import TelegramRetryAfter

        from web.api import avatars

        calls = {"n": 0}

        class FakeBot:
            async def get_chat(self, tid):
                calls["n"] += 1
                raise TelegramRetryAfter(method="getChat", message="flood",
                                         retry_after=5)

        monkeypatch.setattr(avatars.web_runtime, "get_web_bot",
                            lambda: FakeBot())
        with caplog.at_level(logging.DEBUG, logger="web.api.avatars"):
            assert await avatars.fetch_avatar_bytes("chat", 66) is None
            assert await avatars.fetch_avatar_bytes("chat", 66) is None

        assert calls["n"] == 2, "транзиент НЕ кэшируется — повторный запрос"
        assert ("chat", 66) not in avatars._avatar_cache
        recs = _records(caplog)
        assert recs and all(r.levelno == logging.WARNING for r in recs)
        assert all(r.exc_info is None for r in recs)

    @pytest.mark.asyncio
    async def test_chat_display_info_transient_not_cached(
            self, caplog, monkeypatch):
        """Ревью-итер.1 M2: `chat_display_info` чтит транзиентную политику."""
        from aiogram.exceptions import TelegramRetryAfter

        from web.api import avatars

        calls = {"n": 0}

        class FakeBot:
            async def get_chat(self, chat_id):
                calls["n"] += 1
                raise TelegramRetryAfter(method="getChat", message="flood",
                                         retry_after=5)

        monkeypatch.setattr(avatars.web_runtime, "get_web_bot",
                            lambda: FakeBot())
        with caplog.at_level(logging.DEBUG, logger="web.api.avatars"):
            first = await avatars.chat_display_info(77)
            second = await avatars.chat_display_info(77)

        assert first == {"title": None, "photo_file_id": None}
        assert second == first
        assert calls["n"] == 2, "транзиент НЕ кэшируется — повторный запрос"
        assert 77 not in avatars._chat_info_cache
        recs = _records(caplog)
        assert recs and all(r.levelno == logging.WARNING for r in recs)
        assert all(r.exc_info is None for r in recs)

    @pytest.mark.asyncio
    async def test_user_display_info_transient_not_cached(
            self, caplog, monkeypatch):
        """Ревью-итер.1 M2: `user_display_info` (member + photos) не кэширует
        транзиентный сбой — оба вызова повторяются."""
        from aiogram.exceptions import TelegramNetworkError

        from web.api import avatars

        calls = {"n": 0}

        class FakeBot:
            async def get_chat_member(self, chat_id, user_id):
                calls["n"] += 1
                raise TelegramNetworkError(method="getChatMember",
                                           message="network down")

            async def get_user_profile_photos(self, user_id, limit=1):
                calls["n"] += 1
                raise TelegramNetworkError(method="getUserProfilePhotos",
                                           message="network down")

        monkeypatch.setattr(avatars.web_runtime, "get_web_bot",
                            lambda: FakeBot())
        with caplog.at_level(logging.DEBUG, logger="web.api.avatars"):
            first = await avatars.user_display_info(88, 99)
            second = await avatars.user_display_info(88, 99)

        assert first == {"username": None, "photo_file_id": None}
        assert second == first
        assert calls["n"] == 4, "оба транзиента НЕ кэшируются"
        assert (88, 99) not in avatars._username_cache
        assert 99 not in avatars._user_photo_cache
        recs = _records(caplog)
        assert recs and all(r.levelno == logging.WARNING for r in recs)
        assert all(r.exc_info is None for r in recs)


# ═══ 6: R17 — никаких токенов/URL/initData в логах avatars ════════════════

class TestR17LogsClean:
    @pytest.mark.asyncio
    async def test_no_secrets_in_avatar_logs(self, caplog, monkeypatch):
        from aiogram.exceptions import TelegramBadRequest

        from web.api import avatars

        class FakeBot:
            async def get_chat(self, tid):
                raise TelegramBadRequest(method="getChat",
                                         message="chat not found")

            async def get_user_profile_photos(self, tid, limit=1):
                raise RuntimeError("unexpected")

        monkeypatch.setattr(avatars.web_runtime, "get_web_bot",
                            lambda: FakeBot())
        with caplog.at_level(logging.DEBUG, logger="web.api.avatars"):
            await avatars.fetch_avatar_bytes("chat", 1)
            await avatars.user_display_info(2, 3)

        text = " ".join(r.getMessage() for r in _records(caplog))
        for forbidden in ("https://", "api.telegram.org", "initData",
                          "Bearer", "bot_token", "sk-"):
            assert forbidden not in text, f"утечка {forbidden!r} в лог"


# ═══ статические маркеры: helper + порядок + негатив-кэш + прокси ═════════

class TestAvatarCodeMarkers1017:
    def _src(self):
        return open("web/api/avatars.py", encoding="utf-8").read()

    def test_helper_exists_and_policy(self):
        src = self._src()
        assert "def _log_bot_api_failure(" in src
        assert "TelegramBadRequest" in src
        # expected → debug без трейса; неожидаемое → warning с exc_info.
        seg = src.split("def _log_bot_api_failure(")[1].split(
            "# ── обогащение")[0]
        assert "logger.debug(" in seg
        assert "logger.warning(" in seg
        assert "exc_info=True" in seg
        assert "safe_exc_text(exc)" in seg

    def test_telegram_bad_request_before_generic_exception(self):
        """Порядок `except` обязателен: TelegramBadRequest до generic."""
        src = self._src()
        for anchor in ("async def fetch_avatar_bytes",
                       "async def chat_display_info",
                       "async def user_display_info",
                       "async def global_user_display_info"):
            seg = src.split(anchor)[1]
            assert seg.index("except TelegramBadRequest") < seg.index(
                "except Exception"), anchor

    def test_negative_cache_and_proxy_unchanged(self):
        src = self._src()
        assert "_cache_put(_avatar_cache, key, data)" in src
        assert "_cache_put(_chat_info_cache, chat_id, dict(info))" in src
        assert 'media_type="image/jpeg"' in src
        assert "public, max-age=86400" in src
        assert "raise HTTPException(status_code=404" in src


# ═══ 7: brotli — build-time only + Caddy WONTFIX (zstd+gzip) ═══════════════

class TestBrotliDecisionDocs:
    def test_runtime_requirements_have_no_brotli(self):
        runtime = open("requirements.txt", encoding="utf-8").read().lower()
        assert "brotli" not in runtime
        build = open("scripts/requirements-font.txt",
                     encoding="utf-8").read().lower()
        assert "brotli" in build, "build-time источник истины — requirements-font"

    def test_docs_record_wontfix_zstd_gzip(self):
        arch = open("plans/ARCHITECTURE.md", encoding="utf-8").read()
        readme = open("README.md", encoding="utf-8").read()
        assert "WONTFIX" in arch and "zstd" in arch and "brotli" in arch
        assert "zstd" in readme, "README фиксирует zstd+gzip как штатное сжатие"
