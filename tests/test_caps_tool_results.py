"""SMART-EXECUTION-RELIABILITY-01 · C2-01/C3-01: потолки tool-результатов.

Проверяется РЕАЛЬНЫЙ путь данных каждого семейства инструментов:

* поиск — ``SearchAggregator`` поверх ``httpx.MockTransport`` (транспорт
  провайдера) → ``ToolRouter.execute_web_search`` → ToolResult/tool-loop →
  composer → LLM payload → финальный ответ;
* память — ``query_chat_memory``/``get_user_context`` поверх хранилища;
* транскрипты — ``YouTubeTranscriptEngine`` (сегменты провайдера),
  ``transcribe_video`` и ``voice_transcripts`` bundle;
* OCR/Vision — ``analyze_image_bytes`` с transport-стабом провайдера и
  ``recognize_image`` до ToolResult/payload.

Контракт (owner 2026-11-14 §C2/§C3): искусственные символьные/item-потолки
сняты; семантическая выборка сохранена; первая порция не выдаётся за
исчерпывающий результат; физические/провайдерские/транспортные лимиты
остаются и документированы.

RED-proof: на базе ``aca13702`` тесты падают на старых потолках
(4000/3500/20/240/3/20000/4000).
"""
from __future__ import annotations

import copy
import json
import re

import httpx
import pytest

from services import direct_context_composer as comp
from services.llm_client import LLMChatResult, LLMToolCall
from services.search_aggregator import SearchAggregator
from services.tool_loop import chat_with_tools
from services.tool_router import ToolContext, ToolDeps, ToolRouter

TAIL = "CAP-TAIL-MARKER"


class _PipelineLLM:
    """1-й вызов — tool call; 2-й — ответ по маркеру из role:tool."""

    def __init__(self, tool_name: str, arguments: dict, marker: str) -> None:
        self.tool_name = tool_name
        self.arguments = arguments
        self.marker = marker
        self.calls = 0
        self.all_messages: list = []
        self.answer = ""

    async def generate_chat(self, messages, *, temperature=None, tools=None,
                            tool_choice="auto", chat_id=None, **kwargs):
        self.all_messages.append(copy.deepcopy(messages))
        if self.calls == 0:
            self.calls += 1
            return LLMChatResult(
                content=None,
                tool_calls=[LLMToolCall(id="call_1", name=self.tool_name,
                                        arguments=json.dumps(self.arguments))],
                finish_reason="tool_calls")
        tool_content = "\n".join(
            str(m.get("content") or "") for m in messages
            if m.get("role") == "tool")
        found = re.search(re.escape(self.marker), tool_content)
        self.answer = ("Итог: " + found.group(0)) if found else "Итог: потеряно"
        return LLMChatResult(content=self.answer, tool_calls=None,
                             finish_reason="stop")

    async def generate(self, messages, temperature=None, chat_id=None,
                       **kwargs):       # pragma: no cover - fallback не нужен
        self.all_messages.append(copy.deepcopy(messages))
        return "fallback"


class _RecordingRouter(ToolRouter):
    """Реальный ToolRouter + запись фактического выхода для byte-сверки."""

    def __init__(self, deps) -> None:
        super().__init__(deps)
        self.outputs: list[str] = []

    async def dispatch(self, name: str, arguments: dict, ctx) -> str:
        output = await super().dispatch(name, arguments, ctx)
        self.outputs.append(output)
        return output


def _assert_composer_keeps(text: str) -> None:
    """Context composer (budget 0 = OFF) не режет доставленный результат."""
    fragment = comp.ContextFragment(
        kind=comp.KIND_EXTERNAL_EVIDENCE, source_id="caps:1",
        text=text, role=comp.ROLE_MEMORY,
        authority=comp.AUTHORITY_PRIMARY, timestamp_utc=1700000000)
    selection = comp.build_context_selection(
        current_text="вопрос", memory=(fragment,), budget_tokens=0)
    assert selection.memory and selection.memory[0].text == text


async def _run_tool_loop(tool_name: str, arguments: dict, marker: str,
                         router, ctx):
    llm = _PipelineLLM(tool_name, arguments, marker)
    final = await chat_with_tools(
        llm, [{"role": "user", "content": "вопрос"}],
        tools=[{"type": "function"}], router=router, ctx=ctx)
    tool_msg = [m for m in llm.all_messages[1] if m.get("role") == "tool"][0]
    return llm, tool_msg, final


# ═══════════════════════════════════════════════════════════════════════════
# C2-01 / C3-01 · поиск: провайдер → ToolResult → payload → ответ
# ═══════════════════════════════════════════════════════════════════════════

def _tavily_payload(hits: int = 5, snippet_chars: int = 1200) -> dict:
    return {"results": [
        {"title": f"Заголовок {i}",
         "content": ("S" * snippet_chars) + f" {TAIL}-{i}",
         "url": f"https://provider.example/{i}"}
        for i in range(1, hits + 1)]}


def _provider_aggregator(payload: dict) -> tuple[SearchAggregator,
                                                 httpx.AsyncClient]:
    """Реальный агрегатор с transport-стабом провайдера (не fake search)."""

    def _handler(request: httpx.Request) -> httpx.Response:
        if "api.tavily.com" in str(request.url):
            return httpx.Response(200, json=payload, request=request)
        return httpx.Response(500, json={}, request=request)

    client = httpx.AsyncClient(transport=httpx.MockTransport(_handler))
    aggregator = SearchAggregator(tavily_api_key="tav-key", exa_api_key="")
    aggregator._client = client
    return aggregator, client


@pytest.mark.asyncio
async def test_search_provider_result_is_not_trimmed_to_4000() -> None:
    """Шаг 1: провайдер отдал >4000 симв. — инструмент получает весь ответ."""
    aggregator, client = _provider_aggregator(_tavily_payload())
    try:
        text = await aggregator.search("запрос", 4000)
    finally:
        await client.aclose()
    assert len(text) > 4000                      # было жёсткое text[:4000]
    assert f"{TAIL}-5" in text                   # хвост последнего хита цел
    assert text.rstrip().endswith("https://provider.example/5")


@pytest.mark.asyncio
async def test_search_tool_result_reaches_payload_and_answer() -> None:
    """Шаги 2–7: тот же ответ проходит ToolResult → tool-loop → payload."""
    aggregator, client = _provider_aggregator(_tavily_payload())
    ctx = ToolContext(-100, "запрос")
    router = _RecordingRouter(ToolDeps(search=aggregator,
                                       memory=_StubMemory(),
                                       aliases=None))
    try:
        llm, tool_msg, final = await _run_tool_loop(
            "execute_web_search", {"query": "запрос"}, f"{TAIL}-5",
            router, ctx)
    finally:
        await client.aclose()
    delivered = router.outputs[0]
    assert len(delivered) > 4000
    assert tool_msg["content"] == delivered      # байт-в-байт
    assert f"{TAIL}-5" in tool_msg["content"]
    assert final == f"Итог: {TAIL}-5"
    # Context composer не режет уже доставленный результат (budget 0 = OFF).
    fragment = comp.ContextFragment(
        kind=comp.KIND_EXTERNAL_EVIDENCE, source_id="search:1",
        text=delivered, role=comp.ROLE_MEMORY,
        authority=comp.AUTHORITY_PRIMARY, timestamp_utc=1700000000)
    selection = comp.build_context_selection(
        current_text="запрос", memory=(fragment,), budget_tokens=0)
    assert selection.memory and selection.memory[0].text == delivered


class _StubMemory:
    """Минимальное хранилище памяти для tool-loop тестов поиска."""

    async def search_long_term(self, chat_id, keywords_, limit):
        return []

    async def count_mentions(self, chat_id, keywords_, **kwargs):
        return {"count": 0}

    async def vector_search(self, chat_id, query, limit):
        return []

    async def get_rag_context(self, chat_id, query, **kwargs):
        return ""


# ═══════════════════════════════════════════════════════════════════════════
# C2-01 / C3-01 · память: query_chat_memory / get_user_context / dig
# ═══════════════════════════════════════════════════════════════════════════

class _MemoryRows:
    """Хранилище памяти: отдаёт ровно то, что сохранил тест (без срезов)."""

    def __init__(self, rows) -> None:
        self.rows = list(rows)
        self.rag_facts: list = []
        self.context = ""

    async def search_long_term(self, chat_id, keywords_, limit):
        return list(self.rows[:limit])

    async def count_mentions(self, chat_id, keywords_, **kwargs):
        return {"count": len(self.rows)}

    async def vector_search(self, chat_id, query, limit):
        return []

    async def get_rag_facts(self, chat_id, query, **kwargs):
        return list(self.rag_facts)

    async def get_rag_context(self, chat_id, query, **kwargs):
        return self.context


def _memory_rows(count: int, chars: int, *, marker: str) -> list[dict]:
    return [{"id": i, "text": ("M" * chars) + f"-{i}",
             "timestamp": 1700000000 + i, "author_name": "A",
             "tg_message_id": 1000 + i}
            for i in range(1, count + 1)]


@pytest.mark.asyncio
async def test_query_chat_memory_result_not_trimmed_to_3500() -> None:
    """Прежний ``_MEMORY_MAX_SYMBOLS=3500`` обрезал выдачу посимвольно."""
    rows = _memory_rows(40, 200, marker=TAIL)
    rows[-1]["text"] = rows[-1]["text"][:-2] + f"-{TAIL}"
    router = _RecordingRouter(ToolDeps(search=MagicMockSearch(),
                                       memory=_MemoryRows(rows),
                                       aliases=None))
    ctx = ToolContext(-100, "память")
    output = await router.dispatch("query_chat_memory",
                                   {"query": "память"}, ctx)
    assert len(output) > 3500
    assert f"-{TAIL}" in output
    llm, tool_msg, final = await _run_tool_loop(
        "query_chat_memory", {"query": "память"}, f"-{TAIL}", router, ctx)
    assert tool_msg["content"] == output
    assert final == f"Итог: -{TAIL}"
    _assert_composer_keeps(output)


class _FakeAliases:
    def __init__(self, mapping=None) -> None:
        self._aliases = {str(k): str(v) for k, v in (mapping or {}).items()}

    def canon_name(self, name):
        return str(name or "")

    def resolve(self, user_id, nickname=None, username=None):
        return self._aliases.get(str(user_id), str(user_id))


class _FakeMemoryDb:
    """Двойник хранилища (SQLite-эквивалент строк), не подмена инструмента."""

    def __init__(self, facts) -> None:
        self.facts = list(facts)

    async def get_user_context_facts(self, chat_id, target_user, limit, now_ts,
                                     user_id=None):
        return self.facts[:limit]

    async def get_persona_card(self, chat_id, name, limit, now_ts):
        return {"facts": [], "links": []}

    async def get_generated_dossier(self, chat_id, target_user):
        return None

    async def get_recent_messages(self, chat_id, limit):
        return []

    async def search_messages_fts(self, chat_id, match, limit):
        return []

    async def search_graph_facts_fts(self, chat_id, match, limit, now_ts,
                                     include_direct_reply=False,
                                     include_archived=False, **_kw):
        return self.facts[:limit]

    async def get_graph_fact_records(self, fact_ids, status=None):
        wanted = {int(i) for i in fact_ids}
        return [dict(f) for f in self.facts if int(f["id"]) in wanted]


def _fact_row(fact: str, fid: int) -> dict:
    return {"id": fid, "fact": fact, "origin": "chat_history",
            "created_at": 1700000000 + fid, "target_user": "Лёха",
            "weight": 0.8, "status": "confirmed", "tg_message_id": None,
            "message_timestamp": 1700000000 + fid, "kind": "fact"}


@pytest.mark.asyncio
async def test_user_context_explicit_max_items_and_full_fragments() -> None:
    """``max_items=999`` уважается; тексты фактов не режутся до 240."""
    facts = [_fact_row(("F" * 3000) + f"-{i}", i) for i in range(1, 31)]
    facts[-1]["fact"] = facts[-1]["fact"][:-2] + f"-{TAIL}"
    router = _RecordingRouter(ToolDeps(search=MagicMockSearch(),
                                       memory=_MemoryRows([]),
                                       aliases=_FakeAliases({"5": "Лёха"}),
                                       db=_FakeMemoryDb(facts)))
    ctx = ToolContext(-100, "биография", user_id=5)
    raw = await router.dispatch("get_user_context",
                                {"person": "Лёха", "purpose": "biography",
                                 "max_items": 999}, ctx)
    payload = json.loads(raw)
    assert len(payload["facts"]) == 30          # было бы жёстко ≤20
    assert len(payload["facts"][0]["text"]) == 3002   # не 240
    assert payload["truncated"] is False
    assert len(raw) > 4000                       # общего бюджета 4000 нет
    assert f"-{TAIL}" in raw
    llm, tool_msg, final = await _run_tool_loop(
        "get_user_context", {"person": "Лёха", "purpose": "biography",
                             "max_items": 999}, f"-{TAIL}", router, ctx)
    assert tool_msg["content"] == raw
    assert final == f"Итог: -{TAIL}"
    _assert_composer_keeps(raw)


@pytest.mark.asyncio
async def test_user_context_explicit_small_max_items_still_applies() -> None:
    """Семантическая/явная выборка сохранена: max_items=2 → ровно 2 факта."""
    facts = [_fact_row(("F" * 3000) + f"-{i}", i) for i in range(1, 31)]
    router = _RecordingRouter(ToolDeps(search=MagicMockSearch(),
                                       memory=_MemoryRows([]),
                                       aliases=_FakeAliases({"5": "Лёха"}),
                                       db=_FakeMemoryDb(facts)))
    raw = await router.dispatch(
        "get_user_context",
        {"person": "Лёха", "purpose": "biography", "max_items": 2},
        ToolContext(-100, "биография", user_id=5))
    assert len(json.loads(raw)["facts"]) == 2


@pytest.mark.asyncio
async def test_user_context_general_messages_are_full() -> None:
    """Тексты сообщений в general-режиме доставляются целиком (не 240/5)."""
    rows = _memory_rows(10, 500, marker=TAIL)
    router = _RecordingRouter(ToolDeps(search=MagicMockSearch(),
                                       memory=_MemoryRows(rows),
                                       aliases=_FakeAliases({"5": "Лёха"}),
                                       db=None))
    raw = await router.dispatch(
        "get_user_context",
        {"person": "Лёха", "purpose": "general", "max_items": 20},
        ToolContext(-100, "общее", user_id=5))
    payload = json.loads(raw)
    assert len(payload["facts"]) == 10          # было бы ≤5
    assert all(len(f["text"]) >= 502 for f in payload["facts"])
    assert payload["facts"][0]["text"] == ("M" * 500) + "-1"


def test_stats_payload_no_budget_returns_complete_contract() -> None:
    from services.tool_router import _stats_json_payload
    payload = {"metric_id": "m1", "status": "ok", "value": 42,
               "unit": "messages",
               "method": "m", "method_label": "M", "scope": {},
               "coverage": "known_complete",
               "examples": [{"text": "x" * 200}] * 30}
    full = json.loads(_stats_json_payload(payload, 0))
    assert full["value"] == 42
    assert len(full["examples"]) == 30
    explicit = json.loads(_stats_json_payload(payload, 200))
    assert explicit["value"] == 42
    assert explicit["examples"] == []


def test_dig_result_budget_is_explicit_policy_only(monkeypatch) -> None:
    """Заводской ``DIG_MAX_SYMBOLS=3500`` не применяется автоматически."""
    from services import hot_config as hot
    from services import tool_router
    monkeypatch.setattr(hot, "get", lambda key, default=None: default)
    assert tool_router._dig_result_budget() == 0
    result = {"status": "ok", "total_mentions": 1,
              "snippets": ["S" * 3000], "facts": ["F" * 3000]}
    full = json.loads(tool_router._dig_json_payload(result, 0))
    assert len(full["snippets"][0]) == 3000
    assert "truncated" not in full
    monkeypatch.setattr(hot, "get",
                        lambda key, default=None: 4000 if key ==
                        "limits.dig_max_symbols" else default)
    assert tool_router._dig_result_budget() == 4000


class MagicMockSearch:
    """Поиск для тестов памяти: не вызывается (guard)."""

    async def search(self, *args, **kwargs):  # pragma: no cover
        raise AssertionError("search must not be called in memory tests")


# ═══════════════════════════════════════════════════════════════════════════
# C2-01 / C3-01 · транскрипты: YouTube-сегменты и transcribe_video до payload
# ═══════════════════════════════════════════════════════════════════════════

def _youtube_segments(count: int = 40, chars: int = 220) -> list[dict]:
    return [{"start": float(i * 60),
             "text": f"сегмент {i} " + ("T" * chars)}
            for i in range(1, count + 1)]


@pytest.mark.asyncio
async def test_youtube_transcript_full_without_factory_cap(monkeypatch) -> None:
    """Провайдерские сегменты: без max_symbols движок отдаёт ВЕСЬ текст."""
    from services.youtube_transcript_engine import YouTubeTranscriptEngine
    segments = _youtube_segments()
    segments[-1]["text"] += f" {TAIL}"
    engine = YouTubeTranscriptEngine()
    monkeypatch.setattr(engine, "_fetch_ytdlp", lambda video_id: segments)
    monkeypatch.setattr(engine, "_fetch_segments",
                        lambda video_id: segments, raising=False)
    full = await engine.fetch_transcript("video-1", None)
    assert len(full) > 4000                       # было бы срез 20000/4000
    assert f"{TAIL}" in full                      # хвост последнего сегмента
    assert full.count("[") >= 40
    explicit = await engine.fetch_transcript("video-1", 500)
    assert len(explicit) <= 500                   # явный лимит сохранён
    assert YouTubeTranscriptEngine._format(segments, None) == full


class _FakeDownloader:
    def __init__(self, path) -> None:
        self.path = path

    async def download(self, url, quality=None):
        return self.path


class _FakeTranscriber:
    def __init__(self, text: str) -> None:
        self.text = text
        self.calls: list = []

    async def transcribe_voice(self, path, ext, timeout=None):
        self.calls.append((path, ext, timeout))
        return self.text


class _FakeEngine:
    def __init__(self, text: str) -> None:
        self.text = text
        self.args: list = []

    async def fetch_transcript(self, video_id, max_symbols=None,
                               on_retry=None):
        self.args.append((video_id, max_symbols))
        return self.text


class _FakeVideoService:
    def __init__(self, engine) -> None:
        self.engine = engine


@pytest.mark.asyncio
async def test_transcribe_video_link_stt_returns_full_text(tmp_path) -> None:
    """``transcribe_video`` не режет расшифровку до 3500 (link → STT)."""
    media = tmp_path / "voice.ogg"
    media.write_bytes(b"OggS-fake")
    full = ("R" * 9000) + f" {TAIL}"
    transcriber = _FakeTranscriber(full)
    router = _RecordingRouter(ToolDeps(
        search=MagicMockSearch(), memory=_MemoryRows([]), aliases=None,
        downloader=_FakeDownloader(media), transcriber=transcriber))
    ctx = ToolContext(-100, "расшифруй")
    output = await router.dispatch(
        "transcribe_video", {"url": "https://example.com/voice.ogg"}, ctx)
    assert output == full
    assert len(output) > 3500
    llm, tool_msg, final = await _run_tool_loop(
        "transcribe_video", {"url": "https://example.com/voice.ogg"}, TAIL,
        router, ctx)
    assert tool_msg["content"] == output
    assert final == f"Итог: {TAIL}"
    _assert_composer_keeps(output)


@pytest.mark.asyncio
async def test_transcribe_video_youtube_requests_whole_subtitles() -> None:
    """YouTube-путь инструмента просит субтитры БЕЗ cap 20000."""
    engine = _FakeEngine(("S" * 25000) + f" {TAIL}")
    router = _RecordingRouter(ToolDeps(
        search=MagicMockSearch(), memory=_MemoryRows([]), aliases=None,
        video=_FakeVideoService(engine)))
    output = await router.dispatch(
        "transcribe_video",
        {"url": "https://www.youtube.com/watch?v=abcdefghijk"},
        ToolContext(-100, "расшифруй"))
    assert engine.args == [("abcdefghijk", 0)]
    assert output == engine.text
    assert len(output) > 20000


# ═══════════════════════════════════════════════════════════════════════════
# C2-01 / C3-01 · voice_transcripts: весь ряд, явный count, честная страница
# ═══════════════════════════════════════════════════════════════════════════

class _FakeVoiceDb:
    def __init__(self, rows) -> None:
        self.rows = list(rows)

    async def get_voice_window(self, chat_id, since_ts, limit=120):
        return list(self.rows)

    async def get_transcript_states(self, chat_id, ids):
        return {int(r["tg_message_id"]): r for r in self.rows
                if int(r["tg_message_id"]) in {int(i) for i in ids}}

    async def count_voice_sources(self, chat_id, before_tg_id=None):
        return len(self.rows)


def _voice_rows(count: int, *, chars: int = 900) -> list[dict]:
    return [{"id": i, "chat_id": -100, "tg_message_id": 1000 + i,
             "timestamp": 1700000000 + i, "author_name": "A", "user_id": 5,
             "media_type": "voice", "text": ("V" * chars) + f"-{i}",
             "caption": "", "reply_to_id": None, "is_forward": 0,
             "forward_source": "", "sent_at": 1700000000 + i,
             "transcript_status": "ready", "transcript_revision": 1,
             "transcript_updated_at": 1700000000 + i,
             "transcript_reason": ""}
            for i in range(1, count + 1)]


def _voice_query(message_id: int = 2000):
    from types import SimpleNamespace
    return SimpleNamespace(message_id=message_id, reply_to_message=None,
                           quote=None)


@pytest.mark.asyncio
async def test_voice_bundle_returns_whole_run_not_three() -> None:
    from services import voice_transcripts as vt
    rows = _voice_rows(6)
    rows[-1]["text"] = rows[-1]["text"][:-2] + f"-{TAIL}"
    bundle = await vt.resolve_voice_bundle(
        _FakeVoiceDb(rows), chat_id=-100, message=_voice_query(),
        query="разбери эти голосовые")
    assert bundle is not None
    assert len(bundle.items) == 6               # было бы 3
    assert bundle.omitted == 0
    block = vt.render_voice_block(bundle)
    assert rows[0]["text"] in block             # первый фрагмент цел
    assert f"-{TAIL}" in block                  # хвост последнего цел
    assert len(block) > 3500


@pytest.mark.asyncio
async def test_voice_bundle_explicit_count_is_semantic_selection() -> None:
    from services import voice_transcripts as vt
    rows = _voice_rows(6)
    bundle = await vt.resolve_voice_bundle(
        _FakeVoiceDb(rows), chat_id=-100, message=_voice_query(),
        query="расшифруй первые два голосовых")
    assert len(bundle.items) == 2
    assert bundle.refs == ("tg:1001", "tg:1002")
    assert bundle.omitted == 4


@pytest.mark.asyncio
async def test_voice_bundle_page_full_is_marked_not_exhaustive() -> None:
    from services import voice_transcripts as vt
    rows = _voice_rows(120)                      # страница БД насыщена
    bundle = await vt.resolve_voice_bundle(
        _FakeVoiceDb(rows), chat_id=-100, message=_voice_query(),
        query="эти голосовые")
    assert bundle.window_truncated is True
    block = vt.render_voice_block(bundle)
    assert 'window="truncated"' in block
    assert "страница окна чтения заполнена" in block
    short = await vt.resolve_voice_bundle(
        _FakeVoiceDb(_voice_rows(5)), chat_id=-100, message=_voice_query(),
        query="эти голосовые")
    assert short.window_truncated is False


# ═══════════════════════════════════════════════════════════════════════════
# C2-01 / C3-01 · OCR/Vision: провайдер-шаг, полный текст, классификация
# ═══════════════════════════════════════════════════════════════════════════

def _vision_route(*args, **kwargs):
    from services.mca_vision import VisionRoute
    return VisionRoute(source="dedicated", base_url="https://vision.example/v1",
                       model="vlm-1", api_type="openai_compatible",
                       api_key_present=True, config_revision="rev-1")


def _vision_image():
    from services.mca_vision import DownloadedImage
    return DownloadedImage(data=b"\x89PNG\r\n\x1a\n" + b"0" * 64,
                           mime="image/png", declared_mime="image/png",
                           width=640, height=480, byte_size=72)


def _vision_analysis_json(ocr_text: str) -> str:
    return json.dumps({
        "ocr_blocks": [{"text": ocr_text, "bbox": [0, 0, 100, 40]}],
        "visual_description": "скриншот с длинным текстом " + ("D" * 2000),
        "uncertainty": [],
        "self_reported_confidence": 0.9}, ensure_ascii=False)


@pytest.mark.asyncio
async def test_vision_provider_step_keeps_full_ocr_and_real_limit(
        monkeypatch) -> None:
    """Шаг 1: реальный vision-вызов с transport-стабом провайдера отдаёт
    ПОЛНЫЙ OCR (своего символьного потолка в mca_vision нет), а max_tokens —
    физический/конфигурационный предел вывода, не «потолок evidence»."""
    from services import mca_vision
    long_ocr = ("OCR-LINE-" + "Z" * 5000)
    seen: list[dict] = []

    async def transport(url, *, payload, headers, timeout):
        seen.append(payload)
        return 200, {"choices": [{"message": {
            "content": _vision_analysis_json(long_ocr)},
            "finish_reason": "stop"}], "usage": {"total_tokens": 10}}

    monkeypatch.setattr(mca_vision, "api_key_for", lambda route: "test-key")
    route = _vision_route()
    analysis = await mca_vision.analyze_image_bytes(
        _vision_image(), chat_id=-100, route=route, transport=transport)
    assert analysis.status == "ready"
    assert analysis.ocr_blocks[0]["text"] == long_ocr     # целиком
    assert analysis.visual_description.endswith("D" * 2000)
    payload = seen[0]
    assert payload["max_tokens"] == mca_vision.resolve_output_token_limit(
        route)
    assert payload["max_tokens"] >= mca_vision.OUTPUT_TOKEN_FLOOR
    # Явная конфигурация администратора уважается (класс: физический предел).
    monkeypatch.setattr(
        mca_vision.hot, "get",
        lambda key, default=None: 8192 if key ==
        mca_vision.VISION_MAX_OUTPUT_TOKENS_KEY else default)
    assert mca_vision.resolve_output_token_limit(route) == 8192


class _FakeVisionDb:
    """Durable-строки Vision (SQLite-эквивалент), не подмена парсера."""

    def __init__(self, ocr_text: str) -> None:
        self.asset = {"asset_id": "asset-1", "asset_kind": "photo",
                      "tg_message_id": 77, "content_hash": "",
                      "file_unique_id": "u1"}
        self.analysis = {
            "id": 1, "asset_id": "asset-1", "revision": 1,
            "status": "ready", "completed_at": 1700000000,
            "access_scope": "chat", "analysis_schema_version": "v1",
            "quality_profile": "default",
            "ocr_blocks": json.dumps([{"text": ocr_text,
                                       "channel": "untrusted_data"}],
                                     ensure_ascii=False),
            "visual_description": "описание " + ("D" * 2000),
            "uncertainty": "[]", "self_reported_confidence": 0.9,
            "error_reason": ""}

    async def get_media_assets_for_message(self, chat_id, tg_message_id):
        return [self.asset]

    async def get_ready_analysis(self, asset_id, scope,
                                 quality_profile=None):
        return self.analysis

    async def get_smart_message_by_tg_id(self, chat_id, tg_message_id):
        return {"author_name": "A", "user_id": 5, "timestamp": 1700000000}


def _vision_patches(monkeypatch, mca_vision):
    from services import mca_gates
    from services.mca_vision import CapabilityVerdict
    import time as _time
    monkeypatch.setattr(mca_gates, "vision_enabled", lambda: True)
    monkeypatch.setattr(mca_gates, "vision_tool_enabled", lambda: True)

    async def _requested(chat_id=None):
        return True

    monkeypatch.setattr(mca_vision, "resolve_requested", _requested)
    monkeypatch.setattr(
        mca_vision, "cached_capability",
        lambda route: (CapabilityVerdict(capability="ok", reason="",
                                         image_input=True,
                                         checked_at=_time.monotonic()),
                       _time.monotonic()))

    async def _refs(db, **kwargs):
        return []

    monkeypatch.setattr(mca_vision, "derived_fact_source_refs", _refs)


@pytest.mark.asyncio
async def test_recognize_image_tool_result_and_payload_full_ocr(
        monkeypatch) -> None:
    """Шаги 2–7: OCR → recognize_target → recognize_image → tool-loop → payload."""
    from services import mca_vision
    long_ocr = ("OCR-" + "Q" * 5000)
    db = _FakeVisionDb(long_ocr)
    _vision_patches(monkeypatch, mca_vision)
    result = await mca_vision.recognize_target(
        db, chat_id=-100, reply_tg_id=77)
    assert result["status"] == "ready"
    assert result["ocr_blocks"][0]["text"] == long_ocr

    router = _RecordingRouter(ToolDeps(
        search=MagicMockSearch(), memory=_MemoryRows([]), aliases=None,
        db=db))
    ctx = ToolContext(-100, "что на фото?")
    output = await router.dispatch(
        "recognize_image", {"target": {"chat_id": -100, "message_id": 77}},
        ctx)
    payload = json.loads(output)
    assert payload["ocr_blocks"][0]["text"] == long_ocr
    assert len(output) > 5000
    assert "Q" * 5000 in output
    llm, tool_msg, final = await _run_tool_loop(
        "recognize_image", {"target": {"chat_id": -100, "message_id": 77}},
        long_ocr[-24:], router, ctx)
    assert tool_msg["content"] == output
    assert final.startswith("Итог: ")
    _assert_composer_keeps(output)


@pytest.mark.asyncio
async def test_vision_media_render_keeps_full_ocr_and_description(
        monkeypatch) -> None:
    """Потребительский рендер Vision-контекста не режет OCR/описание."""
    from services import mca_vision
    long_ocr = ("SCREEN-" + "W" * 4000)
    db = _FakeVisionDb(long_ocr)
    _vision_patches(monkeypatch, mca_vision)
    data = await mca_vision.render_media_context_async(
        db, chat_id=-100, tg_message_id=77)
    assert data is not None
    assert long_ocr in data["text"]
    assert long_ocr in data["untrusted_ocr_texts"]
    assert ("D" * 2000) in data["text"]
