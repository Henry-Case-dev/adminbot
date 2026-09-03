"""Эпик 04.09.2026 (Часть 1, T-10) — видео-каскад (L1/L2/L3) и клиент.

Покрытие: L1 OK; L1 fail→L2 OK; оба fail→L3 (мок движка/LLM); пустой ответ →
L3; все пусто→LLMBadResponseError; отсутствие ключа→сразу L3; video_client=None
→ ровно старое поведение; payload-форма (video_url); ретрай-политика клиента
(429/5xx/транспорт ≤1 повтор, детерминированные 4xx/пусто/таймаут — сразу);
cleanup_llm_text на пути L1/L2.
"""
import asyncio
import json
from dataclasses import replace
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config.settings import settings
from services import hot_config as hot
from services.llm_client import LLMBadResponseError
from services.video_cascade_client import OpenRouterVideoClient, VideoLevelError
from services.youtube_summarizer_service import (
    YoutubeSummarizerService,
    _canonical_youtube_url,
)
from services.youtube_prompts import YOUTUBE_VIDEO_SYSTEM_PROMPT

VIDEO_ID = "dQw4w9WgXcQ"


def _fake_openai_response(text: str):
    """OpenAI-подобный ответ с choices[0].message.content."""
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text))])


class _StatusError(Exception):
    """Имитация openai.APIStatusError: статус + код + тип."""

    def __init__(self, status_code: int):
        self.status_code = status_code
        super().__init__(f"HTTP {status_code}")


def _client_with(create: AsyncMock) -> OpenRouterVideoClient:
    client = OpenRouterVideoClient(api_key="sk-test")
    completions = SimpleNamespace(create=create)
    client._client = SimpleNamespace(chat=SimpleNamespace(completions=completions))
    client._client_key = "sk-test"
    # W1: _get_client() пересобирает и при смене таймаута — фиксируем
    # актуальный, чтобы инжектированный фейк переиспользовался.
    client._client_timeout = client._current_timeout
    return client


def _no_sleep(monkeypatch):
    monkeypatch.setattr("services.video_cascade_client.asyncio.sleep",
                        AsyncMock())


# ── OpenRouterVideoClient: ретрай-политика и классификация ────────────────


class TestVideoClient:
    @pytest.mark.asyncio
    async def test_success_returns_content(self, monkeypatch):
        _no_sleep(monkeypatch)
        create = AsyncMock(return_value=_fake_openai_response("выжимка ролика"))
        client = _client_with(create)
        text = await client.summarize(model="m1", video_url="https://youtube.com/watch?v=x",
                                      system_prompt="sys", user_text="usr",
                                      timeout=5.0)
        assert text == "выжимка ролика"
        assert create.await_count == 1
        kwargs = create.await_args.kwargs
        assert kwargs["model"] == "m1"

    @pytest.mark.asyncio
    async def test_payload_video_url_form(self):
        """AC-1.3: content = [text, {type: video_url, video_url:{url}}]."""
        create = AsyncMock(return_value=_fake_openai_response("ок"))
        client = _client_with(create)
        await client.summarize(model="m1",
                               video_url="https://www.youtube.com/watch?v=x",
                               system_prompt="sys", user_text="usr", timeout=5.0)
        sent = create.await_args.kwargs["messages"]
        expected = [{"role": "system", "content": "sys"},
                    {"role": "user", "content": [
                        {"type": "text", "text": "usr"},
                        {"type": "video_url",
                         "video_url": {"url": "https://www.youtube.com/watch?v=x"}},
                    ]}]
        assert json.loads(json.dumps(sent)) == json.loads(json.dumps(expected))

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [400, 401, 402, 403, 404, 415, 422])
    async def test_deterministic_4xx_immediate_no_retry(self, monkeypatch, status):
        """AC-1.4: 4xx-детерминированное → мгновенный VideoLevelError('status=…'),
        БЕЗ повтора."""
        _no_sleep(monkeypatch)
        create = AsyncMock(side_effect=_StatusError(status))
        client = _client_with(create)
        with pytest.raises(VideoLevelError) as ei:
            await client.summarize(model="m1", video_url="u", system_prompt="s",
                                   user_text="t", timeout=5.0)
        assert ei.value.reason == f"status={status}"
        assert create.await_count == 1

    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [429, 500, 502, 503])
    async def test_transient_retried_once_then_fails(self, monkeypatch, status):
        """AC-1.4: 429/5xx → 1 повтор (2 попытки), затем VideoLevelError."""
        _no_sleep(monkeypatch)
        create = AsyncMock(side_effect=_StatusError(status))
        client = _client_with(create)
        with pytest.raises(VideoLevelError) as ei:
            await client.summarize(model="m1", video_url="u", system_prompt="s",
                                   user_text="t", timeout=5.0)
        assert ei.value.reason == f"status={status}"
        assert create.await_count == 2

    @pytest.mark.asyncio
    async def test_transient_then_success(self, monkeypatch):
        _no_sleep(monkeypatch)
        calls = {"n": 0}

        async def create(**kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise _StatusError(429)
            return _fake_openai_response("после ретрая")

        client = _client_with(create)
        text = await client.summarize(model="m1", video_url="u", system_prompt="s",
                                      user_text="t", timeout=5.0)
        assert text == "после ретрая"
        assert calls["n"] == 2

    @pytest.mark.asyncio
    async def test_transport_retried_once(self, monkeypatch):
        _no_sleep(monkeypatch)
        import httpx
        create = AsyncMock(side_effect=httpx.ConnectError("socket"))
        client = _client_with(create)
        with pytest.raises(VideoLevelError) as ei:
            await client.summarize(model="m1", video_url="u", system_prompt="s",
                                   user_text="t", timeout=5.0)
        assert ei.value.reason == "transport: ConnectError"
        assert create.await_count == 2

    @pytest.mark.asyncio
    async def test_empty_content_immediate(self, monkeypatch):
        _no_sleep(monkeypatch)
        create = AsyncMock(return_value=_fake_openai_response(None))
        client = _client_with(create)
        with pytest.raises(VideoLevelError) as ei:
            await client.summarize(model="m1", video_url="u", system_prompt="s",
                                   user_text="t", timeout=5.0)
        assert ei.value.reason == "empty content"
        assert create.await_count == 1

    @pytest.mark.asyncio
    async def test_level_timeout_no_retry(self, monkeypatch):
        _no_sleep(monkeypatch)
        create = AsyncMock(side_effect=asyncio.TimeoutError())
        client = _client_with(create)
        with pytest.raises(VideoLevelError) as ei:
            await client.summarize(model="m1", video_url="u", system_prompt="s",
                                   user_text="t", timeout=5.0)
        assert ei.value.reason == "timeout"
        assert create.await_count == 1

    def test_available_depends_on_key(self):
        """available == непустой keys.openrouter_api_key (фолбек на settings)."""
        empty = replace(settings, OPENROUTER_API_KEY="")
        with patch("services.video_cascade_client.settings", empty):
            client = OpenRouterVideoClient()
            assert client.available is False
        filled = replace(settings, OPENROUTER_API_KEY="sk-or-1234")
        with patch("services.video_cascade_client.settings", filled):
            client = OpenRouterVideoClient()
            assert client.available is True


# ── Каскад в YoutubeSummarizerService ──────────────────────────────────────


def _cascade_service(video_client, engine=None, llm=None, memory=None):
    engine = engine or MagicMock()
    engine.fetch_transcript = AsyncMock(return_value="[00:01] субтитры")
    llm = llm or MagicMock()
    llm.generate = AsyncMock(return_value="выжимка по субтитрам")
    return YoutubeSummarizerService(engine, llm, memory=memory,
                                    video_client=video_client), engine, llm


class TestSummarizeCascade:
    def _video_mock(self, text=None, error=None):
        vc = MagicMock()
        vc.available = True
        if error is None:
            vc.summarize = AsyncMock(return_value=text)
        else:
            # список side_effect: L1 падает, L2 (и далее) отдаёт text
            effects = list(error) if isinstance(error, (list, tuple)) else [error]
            if text is not None:
                effects.append(text)
            vc.summarize = AsyncMock(side_effect=effects)
        return vc

    @pytest.mark.asyncio
    async def test_l1_ok_returns_text_no_subtitles(self):
        vc = self._video_mock(text="выжимка из видео")
        service, engine, llm = _cascade_service(vc)
        result = await service.summarize_cascade(VIDEO_ID)
        assert result == "выжимка из видео"
        engine.fetch_transcript.assert_not_called()      # L3 не запускался
        llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_l1_ok_uses_primary_model_and_canonical_url(self):
        vc = self._video_mock(text="ок")
        service, _, _ = _cascade_service(vc)
        await service.summarize_cascade(VIDEO_ID)
        kwargs = vc.summarize.await_args.kwargs
        assert kwargs["model"] == settings.VIDEO_PRIMARY_MODEL
        assert kwargs["video_url"] == _canonical_youtube_url(VIDEO_ID)
        # системный промпт видеорежима с подставленным лимитом
        system = kwargs["system_prompt"]
        assert "{max_symbols}" not in system
        assert str(settings.YOUTUBE_MAX_SYMBOLS) in system
        assert "<video_id>" in kwargs["user_text"]
        assert "Смотри видео и сделай выжимку по правилам" in kwargs["user_text"]
        assert "<transcript>" not in kwargs["user_text"]

    @pytest.mark.asyncio
    async def test_l1_fail_falls_to_l2(self):
        vc = self._video_mock(text="выжимка из видео",
                              error=VideoLevelError("status=400"))
        service, engine, _ = _cascade_service(vc)
        result = await service.summarize_cascade(VIDEO_ID)
        assert result == "выжимка из видео"
        assert vc.summarize.await_count == 2     # L1 + L2
        models = [c.kwargs["model"] for c in vc.summarize.await_args_list]
        assert models == [settings.VIDEO_PRIMARY_MODEL,
                          settings.VIDEO_FALLBACK_MODEL]
        engine.fetch_transcript.assert_not_called()

    @pytest.mark.asyncio
    async def test_both_fail_falls_to_subtitles_l3(self):
        vc = self._video_mock(
            error=[VideoLevelError("status=429"), VideoLevelError("status=429")])
        service, engine, llm = _cascade_service(vc)
        result = await service.summarize_cascade(VIDEO_ID)
        assert result == "выжимка по субтитрам"
        engine.fetch_transcript.assert_awaited_once()
        llm.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_empty_answers_fall_to_l3(self):
        vc = self._video_mock(text="   ")
        service, engine, _ = _cascade_service(vc)
        result = await service.summarize_cascade(VIDEO_ID)
        assert result == "выжимка по субтитрам"
        engine.fetch_transcript.assert_awaited_once()
        # оба уровня пробованы, пустые ответы → L3
        assert vc.summarize.await_count == 2

    @pytest.mark.asyncio
    async def test_all_levels_empty_raises_bad_response(self):
        """Все пусто → хендлер молчание+🗿 через LLMBadResponseError."""
        vc = self._video_mock(text="   ")
        llm = MagicMock()
        llm.generate = AsyncMock(return_value="   ")
        engine = MagicMock()
        engine.fetch_transcript = AsyncMock(return_value="субтитры")
        service = YoutubeSummarizerService(engine, llm, video_client=vc)
        with pytest.raises(LLMBadResponseError):
            await service.summarize_cascade(VIDEO_ID)

    @pytest.mark.asyncio
    async def test_timeout_falls_to_next_level(self):
        vc = self._video_mock(text="выжимка из видео",
                              error=asyncio.TimeoutError())
        service, _, _ = _cascade_service(vc)
        result = await service.summarize_cascade(VIDEO_ID)
        assert result == "выжимка из видео"

    @pytest.mark.asyncio
    async def test_no_key_client_available_false_immediate_l3(self, caplog):
        import logging
        vc = self._video_mock(text="не должно случиться")
        vc.available = False
        service, engine, _ = _cascade_service(vc)
        with caplog.at_level(logging.WARNING):
            result = await service.summarize_cascade(VIDEO_ID)
        assert result == "выжимка по субтитрам"
        vc.summarize.assert_not_called()
        assert any("[video cascade] disabled" in r.message for r in caplog.records)

    @pytest.mark.asyncio
    async def test_video_client_none_is_old_behavior(self):
        """AC-1.2: video_client=None → ровно старое поведение (summarize)."""
        service, engine, llm = _cascade_service(None)
        result = await service.summarize_cascade(VIDEO_ID)
        assert result == "выжимка по субтитрам"
        engine.fetch_transcript.assert_awaited_once()
        llm.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_rag_prefix_used_when_memory_present(self):
        memory = MagicMock()
        memory.get_rag_context = AsyncMock(return_value="<RAG>факты</RAG>")
        vc = self._video_mock(text="ок")
        service, _, _ = _cascade_service(vc, memory=memory)
        await service.summarize_cascade(VIDEO_ID, chat_id=-100,
                                        rag_query="че за видос")
        memory.get_rag_context.assert_awaited_once_with(-100, "че за видос")
        assert "<RAG>факты</RAG>" in vc.summarize.await_args.kwargs["user_text"]

    @pytest.mark.asyncio
    async def test_memorize_not_called_on_video_path(self):
        """FR-5: _memorize_youtube — только на пути субтитров (L3)."""
        spy = []
        with patch("services.youtube_summarizer_service.fire_and_forget",
                   side_effect=lambda coro, tag: spy.append(coro)):
            memory = MagicMock()
            memory.get_rag_context = AsyncMock(return_value="")
            vc = self._video_mock(text="ок")
            service, _, _ = _cascade_service(vc, memory=memory)
            await service.summarize_cascade(VIDEO_ID, chat_id=-100,
                                            rag_query="q")
            assert spy == []                       # L1 — без memorize-хука

    @pytest.mark.asyncio
    async def test_cleanup_applied_to_l1_output(self):
        vc = self._video_mock(text="«ёлочки» — тире")
        service, _, _ = _cascade_service(vc)
        result = await service.summarize_cascade(VIDEO_ID)
        assert result == '"ёлочки" - тире'

    @pytest.mark.asyncio
    async def test_empty_model_skips_level(self, monkeypatch):
        """Пустая модель уровня = ступень отключена (WARNING, уровень пропущен)."""
        class _FakeCache:
            def get(self, key, default):
                if key == "models.video_primary_model":
                    return ""
                return default

        old_cache = hot.get_config_cache()
        hot.set_config_cache(_FakeCache())
        try:
            vc = self._video_mock(text="ок")
            service, _, _ = _cascade_service(vc)
            result = await service.summarize_cascade(VIDEO_ID)
            assert result == "ок"
            # L1 пропущен, сработал L2
            calls = [c.kwargs["model"] for c in vc.summarize.await_args_list]
            assert calls == [settings.VIDEO_FALLBACK_MODEL]
        finally:
            hot.set_config_cache(old_cache)

    def test_video_system_prompt_is_youtube_prompt_variant(self):
        """Промпт видеорежима — копия субтитрового с заменой формулировки."""
        from services.youtube_prompts import YOUTUBE_SYSTEM_PROMPT
        assert YOUTUBE_VIDEO_SYSTEM_PROMPT.count("{max_symbols}") == 1
        assert YOUTUBE_VIDEO_SYSTEM_PROMPT == YOUTUBE_SYSTEM_PROMPT.replace(
            "по предоставленной текстовой расшифровке (субтитрам)",
            "по самому видео (ты видишь кадры и слышишь звук)")
