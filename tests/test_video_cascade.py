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
from services.video_cascade_client import (
    OpenRouterVideoClient,
    VideoLevelError,
    is_refusal_response,
    normalize_for_refusal,
)
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
        vc = self._video_mock(text="выжимка из видео по кадрам")
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
        vc = self._video_mock(text="выжимка по кадрам с RAG-фоном")
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
            vc = self._video_mock(text="выжимка по кадрам без RAG")
            service, _, _ = _cascade_service(vc, memory=memory)
            await service.summarize_cascade(VIDEO_ID, chat_id=-100,
                                            rag_query="q")
            assert spy == []                       # L1 — без memorize-хука

    @pytest.mark.asyncio
    async def test_cleanup_applied_to_l1_output(self):
        """cleanup_llm_text на пути L1; текст после cleanup ≥ порога 15 — не
        отказ (эталон с «ёлочками»/тире как в живых выжимках)."""
        vc = self._video_mock(text="«ёлочки» и тире — длинный пересказ ролика")
        service, _, _ = _cascade_service(vc)
        result = await service.summarize_cascade(VIDEO_ID)
        assert result == '"ёлочки" и тире - длинный пересказ ролика'
        assert vc.summarize.await_count == 1

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
            vc = self._video_mock(text="выжимка от запасной модели по кадрам")
            service, _, _ = _cascade_service(vc)
            result = await service.summarize_cascade(VIDEO_ID)
            assert result == "выжимка от запасной модели по кадрам"
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


# ── Раунд 4 (T-709, AC-C1): маркерный детект отказных ответов ───────────────

class TestIsRefusalResponse:
    """Таблица маркеров (RU/EN, регистры, пунктуация, **…**-обёртка)."""

    @pytest.mark.parametrize("text", [
        # RU
        "не вижу видео, пришли ссылку ещё раз",
        "Я не вижу ролик в этом сообщении",
        "не вижу видеоролик, файл повреждён",
        "не могу посмотреть видео по этой ссылке",
        "не могу посмотреть ролик, доступа нет",
        "извини, не могу просмотреть этот файл",
        "не могу открыть видео, формат не поддерживается",
        "не могу получить доступ к этому видео",
        "не имею доступа к видео, попробуй переслать",
        "нет доступа к видео, ссылка битая",
        "видео недоступно для моей модели",
        "этот ролик недоступен, я пас",
        "видео не загрузилось, попробуй позже",
        "не загрузилось видео, сеть подвела",
        "не получил видео, пришли ещё раз",
        "не могу обработать видео, слишком длинное",
        "не могу разобрать видео без звука",
        "не могу посмотреть сам ролик, только картинку",
        "**не вижу видео**, попробуй переслать файл",
        "НЕ МОГУ ПРОСМОТРЕТЬ ВИДЕО!",
        # EN (с апострофами/тире — нормализуются)
        "there is no video content in your message",
        "I can't see the video, please resend it",
        "I cannot see the video at all",
        "i can't watch the video from this url",
        "cannot watch the video, unsupported format",
        "i cant view the video in this message",
        "cannot view the video, no media received",
        "i don't have access to any video",
        "do not have access to the video file",
        "no access to the video, sorry",
        "unable to view the video content",
        "unable to watch video from this link",
        "cannot access the video, try again later",
        "cant access the video, file missing",
        "video is not available for processing",
        "the video is unavailable, sorry",
        "failed to process the video, try another file",
        "couldn't load the video from the url",
        "i can't view the video, send it as a file",
        "i cannot view the video, resend please",
    ])
    def test_refusal_markers_detected(self, text):
        assert is_refusal_response(text) is True, text

    @pytest.mark.parametrize("text", [
        # содержательные ответы ≥15 символов без маркеров — НЕ отказы
        "в ролике мужик спорит с котом про еду, кот побеждает",
        "краткая выжимка: мем с собакой, все смеются",
        "не вижу смысла спорить — видео просто про монтаж",
        "не могу не отметить, что в кадре отличный свет",
        "смешной ролик про то, как котик гоняет шарик",
    ])
    def test_non_refusal_responses(self, text):
        assert is_refusal_response(text) is False, text

    def test_short_text_is_refusal(self):
        """Короче 15 символов после нормализации — заглушка, не выжимка."""
        assert is_refusal_response("просто смешной ролик") is False  # ровно 17
        assert is_refusal_response("мем с котом") is True            # 11 симв.
        assert is_refusal_response("а" * 14) is True                 # 14 → True
        assert is_refusal_response("а" * 15) is False                # 15 → False
        assert is_refusal_response("   ***   мем   ***  ") is True   # после норм.

    def test_empty_and_punct_handled(self):
        assert is_refusal_response("") is False     # пустота — ДО детекта
        assert is_refusal_response("   ") is False
        assert is_refusal_response(None) is False   # type: ignore[arg-type]

    def test_normalize_for_refusal(self):
        assert normalize_for_refusal("I can't see the video!") == \
            "i cant see the video "
        assert " ".join(normalize_for_refusal("**НЕ ВИЖУ ВИДЕО**").split()) == \
            "не вижу видео"
        assert " ".join(normalize_for_refusal("много   пробелов").split()) == \
            "много пробелов"

    def test_asterisk_wrapped_marker_detected(self):
        """**…**-обёртка из живого ответа free-роута → отказ."""
        assert is_refusal_response("**не вижу видео**, попробуй переслать") \
            is True


# ── Раунд 4 (T-709, AC-C2): отказы в каскаде → следующий уровень/фолбек ────

class TestCascadeRefusals:
    def _video_mock(self, *answers):
        """answers: список ответов уровней по порядку (text | Exception)."""
        vc = MagicMock()
        vc.available = True
        effects = []
        for a in answers:
            if isinstance(a, Exception):
                effects.append(a)
            else:
                effects.append(a)
        vc.summarize = AsyncMock(side_effect=effects)
        return vc

    @pytest.mark.asyncio
    async def test_l1_refusal_l2_success(self, caplog):
        """Отказ на L1 → пробуется L2; юзер получает выжимку L2 (не отказ)."""
        import logging
        vc = self._video_mock("не вижу видео, пришли файл ещё раз",
                              "выжимка по кадрам от minimax")
        service, engine, _ = _cascade_service(vc)
        with caplog.at_level(logging.WARNING):
            result = await service.summarize_cascade(VIDEO_ID)
        assert result == "выжимка по кадрам от minimax"
        assert vc.summarize.await_count == 2
        models = [c.kwargs["model"] for c in vc.summarize.await_args_list]
        assert models == [settings.VIDEO_PRIMARY_MODEL,
                          settings.VIDEO_FALLBACK_MODEL]
        engine.fetch_transcript.assert_not_called()
        assert any("[video cascade] L1 refusal → next" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_l1_refusal_l2_refusal_goes_to_subtitles(self):
        """Оба уровня отказали (YouTube-URL) → L3-субтитры (фолбек)."""
        vc = self._video_mock("не вижу видео", "cannot see the video at all")
        service, engine, llm = _cascade_service(vc)
        result = await service.summarize_cascade(VIDEO_ID)
        assert result == "выжимка по субтитрам"
        assert vc.summarize.await_count == 2
        engine.fetch_transcript.assert_awaited_once()
        llm.generate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_media_url_l1_refusal_l2_success(self):
        vc = self._video_mock("не могу просмотреть видео",
                              "по кадрам: человек идёт по улице")
        service, _, _ = _cascade_service(vc)
        result = await service.summarize_media_url(
            chat_id=-100, video_url="https://x/y.mp4", label="tg-file")
        assert result == "по кадрам: человек идёт по улице"

    @pytest.mark.asyncio
    async def test_media_url_both_refusal_raises_video_level_error(self, caplog):
        """Файловый каскад: L1+L2 отказали → VideoLevelError c 'refusal'
        (хендлер youtube.py:587-590 делает STT-фолбек)."""
        import logging
        vc = self._video_mock("не вижу видео, пришли файл",
                              "i cannot view the video, resend")
        service, _, _ = _cascade_service(vc)
        with caplog.at_level(logging.WARNING):
            with pytest.raises(VideoLevelError) as ei:
                await service.summarize_media_url(
                    chat_id=-100, video_url="https://x/y.mp4", label="tg-file")
        assert "refusal" in str(ei.value)
        assert any("refusal → next" in r.message
                   for r in caplog.records)

    @pytest.mark.asyncio
    async def test_short_stub_treated_as_refusal(self):
        """Короткая заглушка (<15 симв.) L1 → L2 (как отказ)."""
        vc = self._video_mock("мем с котом", "развёрнутая выжимка по кадрам")
        service, _, _ = _cascade_service(vc)
        result = await service.summarize_cascade(VIDEO_ID)
        assert result == "развёрнутая выжимка по кадрам"
        assert vc.summarize.await_count == 2

    @pytest.mark.asyncio
    async def test_normal_shortish_answer_not_refusal(self):
        """Легитимный короткий (но ≥15) ответ не уводит на следующий уровень."""
        vc = self._video_mock("просто смешной ролик с котом и собакой")
        service, engine, _ = _cascade_service(vc)
        result = await service.summarize_cascade(VIDEO_ID)
        assert result == "просто смешной ролик с котом и собакой"
        engine.fetch_transcript.assert_not_called()


# ── Раунд 4 (T-710, AC-C3): дефолты видео-моделей ──────────────────────────

class TestVideoModelDefaults:
    def test_default_model_strings(self):
        """AC-C3: дефолты по живому каталогу OpenRouter (04.09.2026)."""
        assert settings.VIDEO_PRIMARY_MODEL == \
            "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning:free"
        assert settings.VIDEO_FALLBACK_MODEL == "minimax/minimax-m3:free"

    def test_settings_catalog_description_updated(self):
        """Каталог-описания актуализированы (немotron audio+video)."""
        from services.param_catalog import get_by_pg_key
        primary = get_by_pg_key("models.video_primary_model")
        fallback = get_by_pg_key("models.video_fallback_model")
        assert primary is not None and fallback is not None
        assert "nemotron" in primary.description.lower()
        assert "minimax" in fallback.description.lower()
