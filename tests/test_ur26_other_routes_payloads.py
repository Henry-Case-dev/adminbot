"""UNIFIED-REPLY UR-26.6/UR-26.7 — payload/observability прочих маршрутов.

Матрица Architect D4/D5 (base 6123a1469, slicing UR-C-CLOCK):

  * user-facing маршруты с блоком ``<Chat_Time_Context phase="answer">``:
    поиск (digest), страница, YouTube-субтитры, локальный файл,
    мультимодальная выжимка;
  * технические ноги БЕЗ блока и с честным ``clock_included=false``:
    rerank поиска, checkup; tool-путь (snapshot=None) не получает блок —
    seal-инвариант UR-25.6 на ходе;
  * логи на транспортном шве: ``llm.generate`` (через llm_client),
    Supervisor dedicated/stream, dedicated-ноги L1/L2, мультимодальный
    ``video_client.summarize``; поля module/step/chat_id/timezone/as_of_utc/
    config_version/clock_included(+reason); R17 — без текстов payload;
  * окно источников Summary страны не «свежеет» и не переписывает дату
    поисковой выдачи (UR-27.2, D6-граница).

Все LLM-каналы инжектируются: сетевых/платных вызовов нет.

TEST-LIFECYCLE: CONTRACT owner=UNIFIED-REPLY/UR-C-CLOCK (UR-26.6/26.7)
"""
from __future__ import annotations

import datetime
import logging
from unittest.mock import AsyncMock

import pytest

import services.chat_params as chat_params
import services.hot_config as hot_config
import services.search_service as search_mod
import services.web_summarizer_service as web_mod
import services.youtube_summarizer_service as youtube_mod
from services import chat_clock as cc
from services.llm_client import LLMClient
from services.search_service import SearchService
from services.web_summarizer_service import WebSummarizerService
from services.youtube_summarizer_service import YoutubeSummarizerService

pytestmark = [pytest.mark.system2]

CHAT = -1007770001
FROZEN = datetime.datetime(2026, 7, 15, 12, 0,
                           tzinfo=datetime.timezone.utc)


class _Cache:
    """chat_params cache с per-chat override (async root + sync `_items`)."""

    def __init__(self, roots):
        self._roots = dict(roots or {})
        self.updated_at = "2026-11-05T10:00:00Z"
        self._items = {int(cid): (0.0, root, self.updated_at)
                       for cid, root in self._roots.items()}

    async def get_chat_params(self, chat_id):
        return self._roots.get(int(chat_id), {})

    async def get_chat_params_full(self, chat_id):
        return self._roots.get(int(chat_id), {}), self.updated_at


@pytest.fixture()
def clock_env(monkeypatch):
    """Europe/Moscow для CHAT; hot-слои контролируются явно."""
    controlled: dict = {}
    original_get = hot_config.get

    def _get(key, default=None):
        if key in controlled:
            return controlled[key]
        return original_get(key, default)

    monkeypatch.setattr(hot_config, "get", _get)
    monkeypatch.delenv("GOODMORNING_TZ", raising=False)
    chat_params._chat_params_cache = _Cache({
        CHAT: {"overrides": {"limits.chat_timezone": "Europe/Moscow"}}})
    yield controlled
    chat_params._chat_params_cache = None


@pytest.fixture()
def no_owner(monkeypatch):
    for module in (search_mod, web_mod, youtube_mod):
        monkeypatch.setattr(module, "speech_owner_block",
                            AsyncMock(return_value=""))


def _async_noop():
    async def _noop(*args, **kwargs):
        return None
    return _noop


class _Resp:
    status_code = 200
    headers: dict = {}

    def __init__(self, content: str):
        self._payload = {
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 3, "completion_tokens": 2},
        }

    def json(self):
        return self._payload


def _client() -> LLMClient:
    client = LLMClient(base_url="https://primary.example/v1", api_key="k",
                       chat_model="mystery-large", embed_model="embed")
    client._record_global_usage = _async_noop()
    client._record_analytics = _async_noop()
    return client


async def _snapshot(at_utc=FROZEN):
    return await cc.snapshot(CHAT, at_utc=at_utc)


class _Agg:
    def __init__(self, text="результат поиска " * 300):
        self.text = text
        self.calls = []

    async def search(self, query, max_symbols=4000, **kw):
        self.calls.append((query, max_symbols))
        return self.text


class _Extractor:
    def __init__(self, markdown="# Заголовок\nстраница"):
        self.markdown = markdown
        self.calls = []

    async def extract(self, url, max_symbols):
        self.calls.append((url, max_symbols))
        return self.markdown


class _Engine:
    def __init__(self, transcript="[00:00] привет " * 40):
        self.transcript = transcript
        self.calls = []

    async def fetch_transcript(self, video_id, limit=None, on_retry=None):
        self.calls.append((video_id, limit))
        return self.transcript


class _VideoClient:
    available = True

    def __init__(self, text="по кадрам человек идёт по улице"):
        self.text = text
        self.calls = []

    async def summarize(self, **kwargs):
        self.calls.append(dict(kwargs))
        return self.text


class _RecordingLLM:
    def __init__(self, text="ответ"):
        self.text = text
        self.calls = []

    async def generate(self, messages, **kwargs):
        self.calls.append(([dict(m) for m in messages], dict(kwargs)))
        return self.text


def _log_lines(caplog) -> list[str]:
    return [rec.getMessage() for rec in caplog.records
            if "[clock_call]" in rec.getMessage()]


def _clock_args(call) -> dict:
    """kwargs вызова chat_clock.log_clock_call (mock recorder)."""
    return dict(call.kwargs)


def _post_messages(client, index: int = -1) -> list:
    """Финальные messages фактического HTTP-тела (payload — 2-й positional
    аргумент `_post`; fake transport не заполняет `sent`)."""
    call = client._post.await_args_list[index]
    return call.args[1]["messages"]


# ═══ UR-26.6: обязательные user-facing маршруты ══════════════════════════════


class TestUserFacingRoutes:
    @pytest.mark.asyncio
    async def test_search_digest_has_single_answer_block(
            self, clock_env, no_owner, caplog):
        clock_env["flags.search_rerank_enabled"] = False
        snap = await _snapshot()
        client = _client()
        client._post = AsyncMock(return_value=_Resp("выжимка поиска"))
        service = SearchService(_Agg(), client, memory=None)
        with caplog.at_level(logging.INFO, logger="services.chat_clock"):
            out = await service.research("что нового", chat_id=CHAT,
                                         snapshot=snap)
        assert out == "выжимка поиска"
        sent = _post_messages(client)
        user = sent[-1]["content"]
        assert user.count("<Chat_Time_Context") == 1
        meta = cc.outbound_clock_meta(sent)
        assert meta["clock_included"] is True
        assert meta["timezone"] == "Europe/Moscow"
        assert meta["as_of_utc"] == "2026-07-15T12:00:00+00:00"
        assert meta["phase"] == "answer"
        logs = _log_lines(caplog)
        digest = [line for line in logs
                  if "step=digest" in line and "chat_id=%s" % CHAT in line]
        assert digest, logs
        assert "clock_included=true" in digest[-1]
        assert "timezone=Europe/Moscow" in digest[-1]
        assert "SECRET" not in caplog.text

    @pytest.mark.asyncio
    async def test_web_page_has_single_answer_block(
            self, clock_env, no_owner, caplog):
        snap = await _snapshot()
        client = _client()
        client._post = AsyncMock(return_value=_Resp("выжимка страницы"))
        service = WebSummarizerService(_Extractor(), client, memory=None)
        with caplog.at_level(logging.INFO, logger="services.chat_clock"):
            out = await service.summarize("https://example.com/a",
                                          chat_id=CHAT, rag_query="статья",
                                          snapshot=snap)
        assert out == "выжимка страницы"
        sent = _post_messages(client)
        assert sent[-1]["content"].count("<Chat_Time_Context") == 1
        meta = cc.outbound_clock_meta(sent)
        assert meta["clock_included"] is True
        assert meta["timezone"] == "Europe/Moscow"
        assert any("step=page" in line and "clock_included=true" in line
                   for line in _log_lines(caplog))

    @pytest.mark.asyncio
    async def test_youtube_subtitles_has_single_answer_block(
            self, clock_env, no_owner, caplog):
        snap = await _snapshot()
        client = _client()
        client._post = AsyncMock(return_value=_Resp("выжимка видео"))
        service = YoutubeSummarizerService(_Engine(), client, memory=None)
        with caplog.at_level(logging.INFO, logger="services.chat_clock"):
            out = await service.summarize("vid123", chat_id=CHAT,
                                          snapshot=snap)
        assert out == "выжимка видео"
        sent = _post_messages(client)
        assert sent[-1]["content"].count("<Chat_Time_Context") == 1
        meta = cc.outbound_clock_meta(sent)
        assert meta["clock_included"] is True
        assert meta["timezone"] == "Europe/Moscow"
        assert any("step=subtitles" in line and "clock_included=true" in line
                   for line in _log_lines(caplog))

    @pytest.mark.asyncio
    async def test_local_video_file_has_single_answer_block(
            self, clock_env, no_owner, caplog):
        snap = await _snapshot()
        client = _client()
        client._post = AsyncMock(return_value=_Resp("выжимка файла"))
        service = YoutubeSummarizerService(_Engine(), client, memory=None)
        with caplog.at_level(logging.INFO, logger="services.chat_clock"):
            out = await service.summarize_transcript(
                chat_id=CHAT, transcript="много речи про ролик",
                snapshot=snap)
        assert out == "выжимка файла"
        sent = _post_messages(client)
        assert sent[-1]["content"].count("<Chat_Time_Context") == 1
        meta = cc.outbound_clock_meta(sent)
        assert meta["clock_included"] is True
        assert meta["timezone"] == "Europe/Moscow"
        assert any("step=local_file" in line and "clock_included=true" in line
                   for line in _log_lines(caplog))

    @pytest.mark.asyncio
    async def test_multimodal_video_block_and_transport_log(
            self, clock_env, no_owner, monkeypatch):
        snap = await _snapshot()
        video = _VideoClient()
        service = YoutubeSummarizerService(
            _Engine(), _RecordingLLM(), memory=None, video_client=video)
        recorded: list = []
        original = cc.log_clock_call

        def _recorder(**kwargs):
            recorded.append(dict(kwargs))
            return original(**kwargs)

        monkeypatch.setattr(cc, "log_clock_call", _recorder)
        out = await service.summarize_media_url(
            chat_id=CHAT, video_url="https://x/a.mp4", label="tg-file",
            snapshot=snap)
        assert out == video.text
        user_text = video.calls[-1]["user_text"]
        assert user_text.count("<Chat_Time_Context") == 1
        meta = cc.outbound_clock_meta(
            [{"role": "user", "content": user_text}])
        assert meta["clock_included"] is True
        assert meta["timezone"] == "Europe/Moscow"
        multimodal = [entry for entry in recorded
                      if entry.get("channel") == "multimodal"]
        assert multimodal and multimodal[-1]["chat_id"] == CHAT
        assert multimodal[-1]["step"] == "multimodal"
        assert cc.outbound_clock_meta(multimodal[-1]["messages"]) is not None


# ═══ UR-26.6: технические ноги — честный skip ═══════════════════════════════


class TestTechnicalRoutes:
    @pytest.mark.asyncio
    async def test_rerank_has_no_block_and_honest_skip_log(
            self, clock_env, no_owner, caplog):
        clock_env["flags.search_rerank_enabled"] = True
        snap = await _snapshot()
        client = _client()
        client._post = AsyncMock(side_effect=[
            _Resp("выжимка поиска"), _Resp("релевантный фрагмент " * 40)])
        service = SearchService(_Agg(), client, memory=None)
        with caplog.at_level(logging.INFO, logger="services.chat_clock"):
            await service.research("q", chat_id=CHAT, snapshot=snap)
        assert client._post.await_count == 2
        rerank_messages = _post_messages(client, 0)
        digest_messages = _post_messages(client, 1)
        assert cc.outbound_clock_meta(rerank_messages) is None
        assert "<Chat_Time_Context" not in rerank_messages[-1]["content"]
        assert cc.outbound_clock_meta(digest_messages) is not None
        lines = _log_lines(caplog)
        rerank = [line for line in lines if "step=rerank" in line]
        assert rerank, lines
        assert "clock_included=false" in rerank[-1]
        assert "skip_reason=no_time_block" in rerank[-1]
        digest = [line for line in lines if "step=digest" in line]
        assert digest and "clock_included=true" in digest[-1]

    @pytest.mark.asyncio
    async def test_checkup_is_technical_without_block(self, clock_env,
                                                      caplog):
        from services.checkup_service import CheckupService
        client = _client()
        client._post = AsyncMock(return_value=_Resp("диагностический отчёт"))
        service = CheckupService(llm=client, db=None, memory=None,
                                 metrics_enabled=False)
        with caplog.at_level(logging.INFO, logger="services.chat_clock"):
            await service.checkup("лог диагностики", used_fallback=False,
                                  chat_id=CHAT)
        sent = _post_messages(client)
        assert cc.outbound_clock_meta(sent) is None
        assert "<Chat_Time_Context" not in sent[-1]["content"]
        # UR-26.6 (D4): технический вызов обязан оставить ЧЕСТНЫЙ след
        # наблюдения, а не молчание: clock_included=false + причина.
        lines = _log_lines(caplog)
        assert lines, "технический вызов без честной записи часов"
        assert any("clock_included=false" in line
                   and "skip_reason=" in line for line in lines), lines

    @pytest.mark.asyncio
    async def test_tool_path_no_snapshot_has_no_block(self, clock_env,
                                                     no_owner, caplog):
        """Tool-путь передаёт snapshot=None: в tool-result блока нет — на
        ходе остаётся ровно один блок (UR-25.6). Техническая нога обязана
        оставить честную запись clock_included=false."""
        video = _VideoClient()
        service = YoutubeSummarizerService(
            _Engine(), _RecordingLLM(), memory=None, video_client=video)
        await service.summarize_media_url(
            chat_id=CHAT, video_url="https://x/tool.mp4", label="tg-file")
        tool_user = video.calls[-1]["user_text"]
        assert "<Chat_Time_Context" not in tool_user
        client = _client()
        client._post = AsyncMock(return_value=_Resp("tool-subtitles"))
        with caplog.at_level(logging.INFO, logger="services.chat_clock"):
            await YoutubeSummarizerService(_Engine(), client, memory=None
                                           ).summarize("vid-tool", chat_id=CHAT)
        tool_messages = _post_messages(client)
        assert "<Chat_Time_Context" not in tool_messages[-1]["content"]
        tool_lines = [line for line in _log_lines(caplog)
                      if "step=subtitles" in line]
        assert tool_lines and "clock_included=false" in tool_lines[-1]
        assert "skip_reason=" in tool_lines[-1]
        # Тот же сервисный метод в user-facing ходе (snapshot передан) —
        # ровно один блок; seal-инвариант не зависит от tool-хода.
        client2 = _client()
        client2._post = AsyncMock(return_value=_Resp("turn-subtitles"))
        await YoutubeSummarizerService(_Engine(), client2, memory=None
                                       ).summarize(
            "vid-turn", chat_id=CHAT, snapshot=await _snapshot())
        turn_messages = _post_messages(client2)
        assert turn_messages[-1]["content"].count("<Chat_Time_Context") == 1

    @pytest.mark.asyncio
    async def test_multimodal_without_chat_id_logs_honest_skip(
            self, clock_env, monkeypatch):
        """Без chat_id пояс не выдумывается: блока нет, запись честная
        (clock_included=false + skip_reason=no_chat_id)."""
        recorded: list = []
        monkeypatch.setattr(cc, "log_clock_call",
                            lambda **kw: recorded.append(dict(kw)))
        video = _VideoClient()
        service = YoutubeSummarizerService(
            _Engine(), _RecordingLLM(), memory=None, video_client=video)
        await service.summarize_media_url(
            chat_id=None, video_url="https://x/nochat.mp4", label="tg-file")
        assert "<Chat_Time_Context" not in video.calls[-1]["user_text"]
        entry = [e for e in recorded if e.get("channel") == "multimodal"][-1]
        assert entry["chat_id"] is None
        assert entry["skip_reason"] == "no_chat_id"
        assert cc.outbound_clock_meta(entry["messages"]) is None


# ═══ UR-27.2: source date не «свежеет», окно Summary стабильно ═══════════════


class TestSourceDateBoundary:
    @pytest.mark.asyncio
    async def test_search_result_date_is_not_rewritten(self, clock_env,
                                                      no_owner):
        snap = await _snapshot()
        llm = _RecordingLLM(text="ответ")
        service = SearchService(
            _Agg("новость от 01.01.2020: старый материал"), llm, memory=None)
        await service.research("старая новость", chat_id=CHAT, snapshot=snap)
        user1 = llm.calls[-1][0][-1]["content"]
        assert "01.01.2020" in user1
        assert user1.count("01.01.2020") == 1
        # Повторный прогон с ДРУГИМ as_of: текст выдачи байт-в-байт тот же,
        # меняется только блок часов (as_of), дата источника не «свежеет».
        later = await _snapshot(FROZEN + datetime.timedelta(minutes=7))
        await service.research("старая новость", chat_id=CHAT,
                               snapshot=later)
        user2 = llm.calls[-1][0][-1]["content"]
        assert "01.01.2020: старый материал" in user2
        assert cc.outbound_clock_meta([{"role": "user", "content": user1}])[
            "as_of_utc"] == "2026-07-15T12:00:00+00:00"
        assert cc.outbound_clock_meta([{"role": "user", "content": user2}])[
            "as_of_utc"] == "2026-07-15T12:07:00+00:00"


# ═══ UR-26.7: матрица Summary-транспорта (supervisor/dedicated) ══════════════


def _blocked_messages(snap):
    return cc.attach_time_context(
        [{"role": "system", "content": "S"},
         {"role": "user", "content": "стадия summary"}],
        snap, phase=cc.PHASE_ANSWER)


class TestSummaryTransportMatrix:
    @pytest.mark.asyncio
    async def test_supervisor_dedicated_sync_logs_transport(
            self, clock_env, monkeypatch):
        # L1Slot живёт в кластеризаторе; здесь — dedicated-слот Supervisor'а.
        from services.summary_l1_clusterizer import L1Slot
        sup = __import__("services.summary_llm_supervisor",
                         fromlist=["execute_supervised"])
        snap = await _snapshot()
        messages = _blocked_messages(snap)
        client = _client()
        client._post = AsyncMock(return_value=_Resp("ok"))
        recorded: list = []
        monkeypatch.setattr(cc, "log_clock_call",
                            lambda **kw: recorded.append(dict(kw)))
        slot = L1Slot("https://dedicated.example/v1", "ded-model", "k", True)
        content, _usage = await sup.execute_supervised(
            client, messages=messages, operation="l1",
            correlation_id="ur267-sync", chat_id=CHAT,
            module="summary", step="l1_plan", slot=slot)
        assert content == "ok"
        dedicated = [entry for entry in recorded
                     if entry.get("channel") == "dedicated"]
        assert dedicated, recorded
        assert dedicated[-1]["chat_id"] == CHAT
        assert dedicated[-1]["module"] == "summary"
        assert dedicated[-1]["step"] == "l1_plan"
        assert cc.outbound_clock_meta(dedicated[-1]["messages"]) is not None

    @pytest.mark.asyncio
    async def test_supervisor_stream_logs_transport(self, clock_env,
                                                    monkeypatch):
        from services.summary_l1_clusterizer import L1Slot
        sup = __import__("services.summary_llm_supervisor",
                         fromlist=["execute_supervised"])
        snap = await _snapshot()
        messages = _blocked_messages(snap)
        client = _client()
        client.stream_chat_completion = AsyncMock(return_value=("ok", None))
        monkeypatch.setattr(sup, "select_execution_mode",
                            lambda _caps: sup.MODE_STREAM)
        recorded: list = []
        monkeypatch.setattr(cc, "log_clock_call",
                            lambda **kw: recorded.append(dict(kw)))
        slot = L1Slot("https://dedicated.example/v1", "ded-model", "k", True)
        content, _usage = await sup.execute_supervised(
            client, messages=messages, operation="l1",
            correlation_id="ur267-stream", chat_id=CHAT,
            module="summary", step="l1_plan", slot=slot)
        assert content == "ok"
        stream = [entry for entry in recorded
                  if entry.get("channel") == "stream"]
        assert stream, recorded
        assert stream[-1]["chat_id"] == CHAT
        assert cc.outbound_clock_meta(stream[-1]["messages"]) is not None

    @pytest.mark.asyncio
    async def test_supervisor_global_slot_passes_chat_id(self, clock_env,
                                                         monkeypatch):
        sup = __import__("services.summary_llm_supervisor",
                         fromlist=["execute_supervised"])
        snap = await _snapshot()
        messages = _blocked_messages(snap)
        client = _client()
        client.generate = AsyncMock(return_value="ok")
        content, _usage = await sup.execute_supervised(
            client, messages=messages, operation="legacy",
            correlation_id="ur267-global", chat_id=CHAT,
            module="summary", step="single", slot=None)
        assert content == "ok"
        kwargs = client.generate.await_args.kwargs
        assert kwargs.get("chat_id") == CHAT
        assert kwargs.get("module") == "summary"
        assert kwargs.get("step") == "single"

    @pytest.mark.asyncio
    async def test_supervisor_off_dedicated_l1_l2_logs(self, clock_env,
                                                      monkeypatch):
        sup = __import__("services.summary_llm_supervisor",
                         fromlist=["make_wrapped"])
        monkeypatch.setattr(sup, "supervisor_enabled", lambda: False)
        import services.summary_l1_clusterizer as l1mod
        import services.summary_l2_writer as l2mod
        snap = await _snapshot()
        messages = _blocked_messages(snap)
        recorded: list = []
        monkeypatch.setattr(cc, "log_clock_call",
                            lambda **kw: recorded.append(dict(kw)))
        client = _client()
        client._post = AsyncMock(return_value=_Resp("ok"))
        l1_call = l1mod._make_llm_call(
            client, l1mod.L1Slot("https://d/v1", "dm", "k", True),
            "ur267-l1-off", chat_id=CHAT)
        await l1_call(messages)
        l2_call = l2mod._make_llm_call(
            client, l2mod.L2Slot("https://d/v1", "dm", "k", True),
            "ur267-l2-off", chat_id=CHAT)
        await l2_call(messages)
        dedicated = [entry for entry in recorded
                     if entry.get("channel") == "dedicated"]
        assert len(dedicated) >= 2, recorded
        assert {entry["step"] for entry in dedicated} >= {
            l1mod.STEP, l2mod.STEP}
        assert all(entry["chat_id"] == CHAT for entry in dedicated)

    @pytest.mark.asyncio
    async def test_dedicated_node_logs_full_clock_fields(
            self, clock_env, monkeypatch, caplog):
        """D5: dedicated-нога (Supervisor ON sync + Supervisor OFF L1/L2)
        пишет на транспортном шве ВСЕ обязательные поля: module/step/
        chat_id/timezone/as_of_utc/config_version/clock_included (R17 —
        без текстов payload)."""
        from services.summary_l1_clusterizer import L1Slot
        import services.summary_l1_clusterizer as l1mod
        import services.summary_l2_writer as l2mod
        sup = __import__("services.summary_llm_supervisor",
                         fromlist=["execute_supervised"])
        snap = await _snapshot()
        messages = _blocked_messages(snap)
        client = _client()
        client._post = AsyncMock(return_value=_Resp("ok"))
        slot = L1Slot("https://dedicated.example/v1", "ded-model", "k", True)
        with caplog.at_level(logging.INFO, logger="services.chat_clock"):
            await sup.execute_supervised(
                client, messages=messages, operation="l1",
                correlation_id="ur267-fields", chat_id=CHAT,
                module="summary", step="l1_plan", slot=slot)
            monkeypatch.setattr(sup, "supervisor_enabled", lambda: False)
            l1_call = l1mod._make_llm_call(
                client, l1mod.L1Slot("https://d/v1", "dm", "k", True),
                "ur267-fields-l1", chat_id=CHAT)
            await l1_call(messages)
            l2_call = l2mod._make_llm_call(
                client, l2mod.L2Slot("https://d/v1", "dm", "k", True),
                "ur267-fields-l2", chat_id=CHAT)
            await l2_call(messages)
        lines = [line for line in _log_lines(caplog)
                 if "channel=dedicated" in line]
        assert len(lines) >= 3, lines
        for line in lines:
            assert "module=summary" in line, line
            assert "chat_id=%s" % CHAT in line, line
            assert "timezone=Europe/Moscow" in line, line
            assert "as_of_utc=2026-07-15T12:00:00+00:00" in line, line
            assert "config_version=2026-11-05T10:00:00Z" in line, line
            assert "clock_included=true" in line, line
        assert any("step=l1_plan" in line for line in lines), lines
        assert any("step=%s" % l1mod.STEP in line for line in lines), lines
        assert any("step=%s" % l2mod.STEP in line for line in lines), lines

    @pytest.mark.asyncio
    async def test_stream_node_logs_full_clock_fields(self, clock_env,
                                                      monkeypatch, caplog):
        """D5: stream-нога Supervisor'а пишет те же поля с channel=stream
        (llm_client INS-TRACE-запись стрима chat_id не знает — честный
        chat_id даёт именно транспортный лог supervisor'а)."""
        from services.summary_l1_clusterizer import L1Slot
        sup = __import__("services.summary_llm_supervisor",
                         fromlist=["execute_supervised"])
        snap = await _snapshot()
        messages = _blocked_messages(snap)
        client = _client()
        client.stream_chat_completion = AsyncMock(return_value=("ok", None))
        monkeypatch.setattr(sup, "select_execution_mode",
                            lambda _caps: sup.MODE_STREAM)
        slot = L1Slot("https://dedicated.example/v1", "ded-model", "k", True)
        with caplog.at_level(logging.INFO, logger="services.chat_clock"):
            await sup.execute_supervised(
                client, messages=messages, operation="l1",
                correlation_id="ur267-stream-fields", chat_id=CHAT,
                module="summary", step="l1_plan", slot=slot)
        lines = [line for line in _log_lines(caplog)
                 if "channel=stream" in line]
        assert len(lines) == 1, lines
        line = lines[0]
        assert "module=summary" in line
        assert "step=l1_plan" in line
        assert "chat_id=%s" % CHAT in line
        assert "timezone=Europe/Moscow" in line
        assert "as_of_utc=2026-07-15T12:00:00+00:00" in line
        assert "config_version=2026-11-05T10:00:00Z" in line
        assert "clock_included=true" in line

    @pytest.mark.asyncio
    async def test_supervisor_on_wrapped_l1_threads_chat_id(
            self, clock_env, monkeypatch):
        sup = __import__("services.summary_llm_supervisor",
                         fromlist=["make_wrapped"])
        import services.summary_l1_clusterizer as l1mod
        monkeypatch.setattr(sup, "supervisor_enabled", lambda: True)
        snap = await _snapshot()
        messages = _blocked_messages(snap)
        client = _client()
        client._post = AsyncMock(return_value=_Resp("ok"))
        recorded: list = []
        monkeypatch.setattr(cc, "log_clock_call",
                            lambda **kw: recorded.append(dict(kw)))
        wrapped = sup.make_wrapped(
            client, l1mod.L1Slot("https://d/v1", "dm", "k", True),
            "ur267-wrap", operation="l1", module="summary",
            step="l1_plan", chat_id=CHAT)
        assert wrapped is not None
        await wrapped(messages)
        dedicated = [entry for entry in recorded
                     if entry.get("channel") == "dedicated"]
        assert dedicated and dedicated[-1]["chat_id"] == CHAT
        assert cc.outbound_clock_meta(dedicated[-1]["messages"]) is not None

    @pytest.mark.asyncio
    async def test_clock_log_does_not_include_payload_text(self, clock_env,
                                                           caplog):
        snap = await _snapshot()
        messages = cc.attach_time_context(
            [{"role": "user", "content": "СЕКРЕТНЫЙ-ТЕКСТ-ПОЛЬЗОВАТЕЛЯ"}],
            snap, phase=cc.PHASE_ANSWER)
        with caplog.at_level(logging.INFO, logger="services.chat_clock"):
            cc.log_clock_call(module="m", step="s", chat_id=CHAT,
                              messages=messages, channel="dedicated")
        assert "[clock_call]" in caplog.text
        assert "СЕКРЕТНЫЙ-ТЕКСТ-ПОЛЬЗОВАТЕЛЯ" not in caplog.text
