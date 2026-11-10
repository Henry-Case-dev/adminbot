"""Даты публикации web-источников доходят до L2 — и только реальные.

Проблема (независимый review на 92070d0e): дата источника не доезжала до
модели вообще — ``_parse_search_sources`` создавал ``SourceRecord(published_at="")``,
``SearchAggregator._format_hits`` печатал только ``title/snippet/url``,
``EvidenceSource`` не имел поля даты, а ``build_evidence_pack`` рендерил
``[ИСТОЧНИК N | tool | status]`` без даты. Требование владельца: L2 получает
«источник / дата / ограничения», при этом дата НЕ выдумывается.

Реальные поля провайдеров (проверено по документации):
  * Exa ``/search`` → ``results[].publishedDate`` — ISO 8601 UTC, отдаётся по
    умолчанию («An estimate of the creation date, from parsing HTML content»);
  * Tavily ``/search`` → ``results[].published_date`` — RFC 2822 в примере
    доки («Tue, 11 Mar 2025 17:00:00 GMT»), отдаётся только при
    ``include_published_date`` (или ``topic=news``), иначе поля нет;
  * DuckDuckGo ``DDGS().text()`` → только ``title``/``href``/``body``, даты
    нет вовсе.

TEST-LIFECYCLE: CONTRACT owner=search-source-dates
"""
import json
import re

import httpx
import pytest

from services import direct_execution as _dx
from services import direct_l1 as _l1
from services import factcheck_planner as _fsp
from services import search_aggregator as _sa
from services import tool_router as _tr
from services.direct_execution import EvidenceSource, ChainResult
from services.tool_router import ToolContext, ToolDeps, ToolRouter

pytestmark = [pytest.mark.system2]

CHAT_ID = -1001234567890


# ── провайдерский слой: MockTransport на реальном SearchAggregator ──────────


def _aggregator(handler, monkeypatch):
    """SearchAggregator с httpx.MockTransport (прецедент test_search_aggregator)."""
    requests = []

    def _handler(request):
        requests.append(request)
        return handler(request)

    transport = httpx.MockTransport(_handler)
    original = httpx.AsyncClient

    monkeypatch.setattr(
        "services.search_aggregator.httpx.AsyncClient",
        lambda **kw: original(transport=transport, **kw))
    return _sa.SearchAggregator(tavily_api_key="tav-key",
                                exa_api_key="exa-key"), requests


def _json_handler(payload):
    def handler(request):
        return httpx.Response(200, json=payload, request=request)

    return handler


EXA_HIT_WITH_DATE = {
    "results": [{
        "title": "Курс биткоина",
        "url": "https://exa.example/btc",
        "text": "биткоин вырос на 4%",
        "publishedDate": "2025-03-11T00:00:00.000Z",
    }]
}
TAVILY_HIT_WITH_DATE = {
    "results": [{
        "title": "Курс биткоина",
        "url": "https://tavily.example/btc",
        "content": "биткоин вырос на 4%",
        "published_date": "Tue, 11 Mar 2025 17:00:00 GMT",
    }]
}


@pytest.mark.asyncio
class TestProviderFieldPropagation:
    """Дата провайдера → нормализованная ISO-дата в тексте выдачи."""

    @pytest.mark.asyncio
    async def test_exa_published_date_reaches_feed(self, monkeypatch):
        agg, requests = _aggregator(_json_handler(EXA_HIT_WITH_DATE),
                                    monkeypatch)
        agg._tavily_api_key = ""          # уровень-1 выключен → отвечает Exa
        text = await agg.search("курс биткоина", 4000)
        assert "дата публикации: 2025-03-11" in text
        assert "https://exa.example/btc" in text
        assert len(requests) == 1, "один сетевой вызов на поиск"

    @pytest.mark.asyncio
    async def test_exa_request_payload_not_changed(self, monkeypatch):
        """Дату читаем из ответа, запрос к провайдеру не расширяем."""
        agg, requests = _aggregator(_json_handler(EXA_HIT_WITH_DATE),
                                    monkeypatch)
        agg._tavily_api_key = ""
        await agg.search("курс биткоина", 4000)
        body = json.loads(requests[0].content)
        assert set(body) == {"query", "numResults", "type", "contents"}

    @pytest.mark.asyncio
    async def test_tavily_published_date_rfc2822_normalised(self, monkeypatch):
        agg, requests = _aggregator(_json_handler(TAVILY_HIT_WITH_DATE),
                                    monkeypatch)
        text = await agg.search("курс биткоина", 4000)
        assert "дата публикации: 2025-03-11" in text
        assert len(requests) == 1, "один сетевой вызов на поиск"
        body = json.loads(requests[0].content)
        # Параметры запроса НЕ менялись (никакого include_published_date).
        assert set(body) == {"query", "max_results", "search_depth"}

    @pytest.mark.asyncio
    async def test_hit_without_date_gets_no_date_line(self, monkeypatch):
        payload = {"results": [{"title": "t", "url": "https://e/1",
                                "text": "s"}]}
        agg, _ = _aggregator(_json_handler(payload), monkeypatch)
        agg._tavily_api_key = ""
        text = await agg.search("запрос", 4000)
        assert "дата публикации" not in text
        assert text.strip().endswith("https://e/1")

    @pytest.mark.asyncio
    async def test_ddg_level_reports_no_date_and_no_http_calls(self,
                                                               monkeypatch):
        class _FakeDDGS:
            def __init__(self, timeout=None):
                self.timeout = timeout

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

            def text(self, query, max_results=5):
                return [{"title": "t", "href": "https://d/1", "body": "s"}]

        monkeypatch.setattr(_sa, "DDGS", _FakeDDGS)
        calls = []
        original = httpx.AsyncClient
        monkeypatch.setattr(
            "services.search_aggregator.httpx.AsyncClient",
            lambda **kw: calls.append(kw) or original(**kw))
        agg = _sa.SearchAggregator(tavily_api_key="", exa_api_key="")
        text = await agg.search("запрос", 4000)
        assert "дата публикации" not in text
        assert calls == [], "уровень DDG не делает HTTP-вызовов"


# ── нормализация значения: мусор не превращается в дату ─────────────────────


class TestDateNormalisation:
    @pytest.mark.parametrize("raw,expected", [
        ("2025-03-11T00:00:00.000Z", "2025-03-11"),
        ("Tue, 11 Mar 2025 17:00:00 GMT", "2025-03-11"),
        ("2025-03-11", "2025-03-11"),
    ])
    def test_real_provider_formats(self, raw, expected):
        assert _sa.normalise_publication_date(raw) == expected

    @pytest.mark.parametrize("raw", [
        "", None, "не дата", "2025-13-45", "31 февраля 2025",
        "2025-03-11 вспомогательный хвост",
    ])
    def test_garbage_is_not_turned_into_a_date(self, raw):
        assert _sa.normalise_publication_date(raw) == ""

    def test_malformed_marker_line_does_not_become_a_date(self):
        """Кривая строка метки: даты нет и в сниппете её тоже нет."""
        feed = "Заголовок\nсниппет\nдата публикации: 2025-13-45\nhttps://e/1"
        records = _dx._parse_search_sources(feed, tool="execute_web_search")
        assert records[0].published_at == ""
        assert "2025-13-45" not in records[0].snippet
        assert records[0].snippet == "сниппет"
        assert records[0].url == "https://e/1"


# ── evidence pack: строка источника и трасса ────────────────────────────────


def _plan(**over):
    return _l1.normalize_l1_plan(dict({"action": "reply", "confidence": 0.9,
                                       **over}))


class _SearchProvider:
    """Подменный агрегатор: отдаёт готовый текст выдачи, считает вызовы."""

    def __init__(self, text):
        self.text = text
        self.queries = []

    async def search(self, query, max_symbols=4000, **kw):
        self.queries.append(str(query))
        return self.text


async def _run_phase(text, *, capacity_chars=None):
    search = _SearchProvider(text)
    router = ToolRouter(ToolDeps(search=search, memory=object()))
    result = await _dx.run_tool_phase(
        plan=_plan(knowledge_origin="web_search"), router=router,
        ctx=ToolContext(CHAT_ID, "курс биткоина"), query="курс биткоина",
        chat_id=CHAT_ID, correlation_id="corr-dates",
        tool_schemas=[{"function": {"name": "execute_web_search",
                                    "description": "search"}}],
        required_caps=("web_search",), capacity_chars=capacity_chars)
    return result, search


class TestEvidencePackSourceLine:
    @pytest.mark.asyncio
    async def test_pack_line_and_trace_carry_provider_date(self, monkeypatch):
        """Полный путь: ответ провайдера → текст выдачи → evidence pack → трасса."""
        agg, requests = _aggregator(_json_handler(TAVILY_HIT_WITH_DATE),
                                    monkeypatch)
        feed = await agg.search("курс биткоина", 4000)
        assert len(requests) == 1
        result, search = await _run_phase(feed)
        assert len(search.queries) == 1, "один поиск за ход"
        header = next(line for line in result.pack.text.splitlines()
                      if line.startswith("[ИСТОЧНИК 1"))
        assert header == ("[ИСТОЧНИК 1 | execute_web_search | ok | "
                          "дата публикации: 2025-03-11]")
        # Тело блока тоже несёт дату — она реально видна модели.
        assert "дата публикации: 2025-03-11" in result.pack.text
        # Структурное поле источника (per-hit) и машинная трасса.
        assert [s.published_at for s in result.evidence.sources] == \
            ["2025-03-11"]
        # Одиночный хит — дата конкретна и на уровне источника тоже.
        assert result.pack.sources[0].published_at == "2025-03-11"
        trace = result.evidence.trace_fields()
        assert trace["source_dates"] == ["2025-03-11"]
        assert trace["published_at_status"] == "reported"

    @pytest.mark.asyncio
    async def test_pack_states_absence_without_inventing(self):
        feed = ("Заголовок\nсниппет без даты\nhttps://ddg.example/1")
        result, _ = await _run_phase(feed)
        header = next(line for line in result.pack.text.splitlines()
                      if line.startswith("[ИСТОЧНИК 1"))
        assert header == ("[ИСТОЧНИК 1 | execute_web_search | ok | "
                          "дата публикации не сообщается источником]")
        assert result.evidence.sources[0].published_at == ""
        trace = result.evidence.trace_fields()
        assert trace["source_dates"] == []
        assert trace["published_at_status"] == "not_reported"
        # Никакой «пустой»/нулевой даты в пакете не появляется.
        assert "дата публикации:" not in result.pack.text

    @pytest.mark.asyncio
    async def test_several_dates_are_not_collapsed_into_one(self):
        feed = ("A\nпервый\nдата публикации: 2025-03-11\nhttps://e/1\n\n"
                "B\nвторой\nдата публикации: 2024-12-01\nhttps://e/2")
        result, _ = await _run_phase(feed)
        header = next(line for line in result.pack.text.splitlines()
                      if line.startswith("[ИСТОЧНИК 1"))
        assert header == ("[ИСТОЧНИК 1 | execute_web_search | ok | "
                          "даты публикации — у каждого источника в блоке]")
        assert [s.published_at for s in result.evidence.sources] == \
            ["2025-03-11", "2024-12-01"]
        assert result.evidence.trace_fields()["source_dates"] == \
            ["2025-03-11", "2024-12-01"]

    @pytest.mark.asyncio
    async def test_one_dated_hit_of_three_is_not_the_block_date(self):
        """Дата ОДНОГО хита не печатается как дата всего блока (review 791e4009).

        Структурные записи уже честные (``2025-03-11``, ``""``, ``""``), а
        заголовок блока печатал единственную найденную дату — модель читала её
        как дату всей выдачи."""
        feed = ("A\nпервый\nдата публикации: 2025-03-11\nhttps://e/1\n\n"
                "B\nвторой\nhttps://e/2\n\n"
                "C\nтретий\nhttps://e/3")
        result, _ = await _run_phase(feed)
        header = next(line for line in result.pack.text.splitlines()
                      if line.startswith("[ИСТОЧНИК 1"))
        assert header == ("[ИСТОЧНИК 1 | execute_web_search | ok | "
                          "даты публикации — у каждого источника в блоке]")
        assert "дата публикации: 2025-03-11]" not in header
        assert [s.published_at for s in result.evidence.sources] == \
            ["2025-03-11", "", ""]
        # Агрегат источника НЕ приписывает дату одного хита всей выдаче
        # (review 82d21889, DEFECT 2).
        assert result.pack.sources[0].published_at == ""
        # Факт «какая-то дата сообщена» при этом не теряется.
        assert result.evidence.trace_fields()["source_dates"] == ["2025-03-11"]

    @pytest.mark.asyncio
    async def test_fetch_article_own_date_is_used(self):
        """Дата, которую вернул сам инструмент (метаданные страницы)."""
        payload = json.dumps({"status": "ok", "url": "https://b/9",
                              "published_at": "2024-05-06T10:00:00Z",
                              "markdown": "текст статьи"})
        assert _dx._source_publication_date("fetch_article", payload) == \
            "2024-05-06"
        src = EvidenceSource(tool="fetch_article", status="ok", content=payload,
                             published_at="2024-05-06")
        pack = _dx.build_evidence_pack(
            ChainResult("", evidence_sources=[src]), capacity_chars=4000)
        header = next(line for line in pack.text.splitlines()
                      if line.startswith("[ИСТОЧНИК 1"))
        assert header == ("[ИСТОЧНИК 1 | fetch_article | ok | "
                          "дата публикации: 2024-05-06]")

    def test_local_tool_line_has_no_date_part(self):
        """У локального инструмента понятия «дата публикации» нет — строка прежняя."""
        src = EvidenceSource(tool="dig_into_lore", status="ok",
                             content="лор чата")
        pack = _dx.build_evidence_pack(
            ChainResult("", evidence_sources=[src]), capacity_chars=4000)
        assert "[ИСТОЧНИК 1 | dig_into_lore | ok]" in pack.text
        assert "дата публикации" not in pack.text


# ── метка даты — метаданные, а не доказательство (review 791e4009) ──────────


DEMANDED_CLAIM = "биткоин вырос на 11 процентов за неделю"
FEED_WITH_DATE_LINE = ("Курс биткоина\nбиткоин вырос на 4% за неделю\n"
                       "дата публикации: 2025-03-11\nhttps://e/1")
FEED_WITHOUT_DATE_LINE = "Курс биткоина\nбиткоин вырос на 4% за неделю\nhttps://e/1"


class _ClaimItem:
    """Единственная реплика чата: текст тезиса (интерфейс claim-item)."""

    def __init__(self, text):
        self.text = text
        self.author = "u"
        self.source = "chat"
        self.anchor_tg_message_id = 1


class TestDateLineIsNotEvidence:
    """BLOCKER 1: «11» из «2025-03-11» подтверждало требование «11 процентов».

    Метка даты публикации — наши метаданные о КОГДА опубликован источник, а не
    его утверждение. Тест держит контракт: наличие/отсутствие строки даты НЕ
    меняет роль источника и силу привязки к тезису.
    """

    def _claim(self):
        unit = _fsp.build_claim_units([_ClaimItem(DEMANDED_CLAIM)],
                                      DEMANDED_CLAIM)[0]
        assert unit.metrics == ("11 процентов",), "число тезиса — 11 %"
        return unit

    def test_date_line_does_not_change_role_or_strong_binding(self):
        unit = self._claim()
        dated = _fsp.evidence_refs_from_search(FEED_WITH_DATE_LINE)[0]
        plain = _fsp.evidence_refs_from_search(FEED_WITHOUT_DATE_LINE)[0]
        dated_rel = _fsp._relevance_for(dated, unit)
        plain_rel = _fsp._relevance_for(plain, unit)
        # Роль и привязка одинаковы: дата не участвует в проверке.
        assert dated_rel.role == plain_rel.role
        assert _fsp._strong_binding(dated, unit) is \
            _fsp._strong_binding(plain, unit)
        # И одинаковы правильно: источник говорит про 4 %, а не про 11 %.
        assert dated_rel.role == _sa.EVIDENCE_ROLE_QUALIFIES
        assert dated_rel.number_hits == 0
        assert dated_rel.number_mismatch is True
        assert _fsp._strong_binding(dated, unit) is False

    def test_general_matching_gate_strips_the_label(self):
        """Метку снимает общий гейт сопоставления, а не только планировщик."""
        text = "биткоин вырос на 4% за неделю\nдата публикации: 2025-03-11"
        verdict = _sa.claim_relevance(
            text, claim_text=DEMANDED_CLAIM,
            metrics=tuple(sorted(_sa._numbers_in("11 процентов"))))
        assert verdict.number_hits == 0, "цифры даты не считаются числами тезиса"
        assert verdict.strong is False
        # Дата остаётся видимой в тексте источника (её не выкидываем из выдачи),
        # и памятка без значения не превращается в мусор.
        assert "2025-03-11" in text
        assert "не сообщается" in _sa.strip_publication_labels(
            "дата публикации не сообщается источником")

    # ── review 82d21889, DEFECT 1: значение снимается ЦЕЛИКОМ ──────────────

    RFC_VALUE = "Tue, 11 Mar 2025 17:00:00 GMT"
    RFC_ENV = ("Биткоин. биткоин вырос на 4 процента за неделю дата публикации: "
               "Tue, 11 Mar 2025 17:00:00 GMT")
    PLAIN_ENV = "Биткоин. биткоин вырос на 4 процента за неделю"

    @pytest.mark.parametrize("value", [
        "2025-03-11",
        "2025-03-11T00:00:00.000Z",
        "Tue, 11 Mar 2025 17:00:00 GMT",
        "Wed, 12 Mar 2025 17:00:00 GMT",
        "11 Mar 2025 17:00:00 GMT",
        "11 марта 2025",
        "11.03.2025",
    ])
    def test_label_value_is_removed_completely(self, value):
        """Ни одна цифра даты не остаётся в тексте для сопоставления."""
        stripped = _sa.strip_publication_labels(
            f"биткоин вырос на 4 процента дата публикации: {value}")
        assert "2025" not in stripped and "11" not in stripped
        assert _sa._numbers_in(stripped) == {"4"}
        assert stripped.startswith("биткоин вырос на 4 процента")

    def test_rfc_label_keeps_the_rest_of_the_text(self):
        """Метка со значением снимается, остальной текст строки сохраняется."""
        text = ("заголовок\nсниппет\nдата публикации: "
                "Tue, 11 Mar 2025 17:00:00 GMT\nhttps://e/1")
        stripped = _sa.strip_publication_labels(text)
        assert "Tue" not in stripped and "2025" not in stripped
        assert "заголовок" in stripped and "сниппет" in stripped
        assert "https://e/1" in stripped

    def test_rfc_dated_support_same_verdict_via_planner(self):
        """Потребитель №1: `factcheck_planner._relevance_for`."""
        unit = self._claim()
        dated = _fsp.EvidenceRef(evidence_id="", url="https://e/1",
                                 support=self.RFC_ENV,
                                 source_kind="secondary", published_at=None)
        plain = _fsp.EvidenceRef(evidence_id="", url="https://e/1",
                                 support=self.PLAIN_ENV,
                                 source_kind="secondary", published_at=None)
        dated_rel = _fsp._relevance_for(dated, unit)
        plain_rel = _fsp._relevance_for(plain, unit)
        assert dated_rel.role == plain_rel.role
        assert _fsp._strong_binding(dated, unit) is \
            _fsp._strong_binding(plain, unit) is False
        assert dated_rel.number_hits == 0, "день месяца не является числом тезиса"

    def test_rfc_dated_evidence_same_verdict_via_evidence_policy(self):
        """Потребитель №2: `evidence_policy._supported` (egress-проверка)."""
        from services import evidence_policy as _ep

        assert _ep._supported(DEMANDED_CLAIM, self.RFC_ENV) is \
            _ep._supported(DEMANDED_CLAIM, self.PLAIN_ENV)
        # Общий числовой примитив обоих потребителей даты не видит.
        assert _sa._numbers_in(_sa.strip_publication_labels(self.RFC_ENV)) == \
            _sa._numbers_in(self.PLAIN_ENV)


# ── отсутствие регрессий: вызовы, обрезка, ограничения ──────────────────────


class TestNoBehaviourDrift:
    @pytest.mark.asyncio
    async def test_truncation_marker_and_limitations_text_unchanged(self):
        """Дата в заголовке не меняет ни механизм обрезки, ни текст ограничений."""
        body = "очень длинный источник " * 200
        dated = f"Заголовок\n{body}\nдата публикации: 2025-03-11\nhttps://e/1"
        undated = f"Заголовок\n{body}\nhttps://e/1"
        dated_run, _ = await _run_phase(dated, capacity_chars=600)
        plain_run, _ = await _run_phase(undated, capacity_chars=600)
        for run in (dated_run, plain_run):
            assert "[…обрезано: показано 600/" in run.pack.text
            assert run.pack.text.endswith(
                "Недостающие данные НЕ выдумывай — честно скажи, что эта "
                "часть недоступна.")
            assert run.pack.complete is False
        # Формулировки ограничений те же; отличаются только счётчики (дата
        # входит в объём выдачи инструмента, а не в бюджет её текста).
        shape = [re.sub(r"\d+", "N", item)
                 for item in dated_run.pack.limitations]
        plain_shape = [re.sub(r"\d+", "N", item)
                       for item in plain_run.pack.limitations]
        assert shape == plain_shape
        assert dated_run.pack.sources[0].delivered_chars == \
            plain_run.pack.sources[0].delivered_chars == 600

    def test_compaction_keeps_every_date_and_url(self):
        feed = "\n\n".join(
            "Заголовок %d\n%s\nдата публикации: 2025-03-0%d\nhttps://e/%d"
            % (i, "сниппет " * 60, i + 1, i) for i in range(5))
        truncation = _tr._compact_search_candidates(feed, 400)
        assert truncation.truncated is True
        assert truncation.text.count("https://e/") == 5, "URL не теряются"
        assert truncation.text.count("дата публикации:") == 5, "даты не теряются"
        assert len(truncation.text) <= 400, "лимит выдачи соблюдён"
        # Даты не срезаются вместе со сниппетом: они отдельные метаданные.
        assert "дата публикации: 2025-03-05" in truncation.text
