"""ASAP-EVIDENCE-ROUTING-01 v3 — Dynamic Evidence Window / source fetch /
claim-bound reuse (P0, worktree lane `evol/impl`).

Проверяются контрактные подмножества сценариев §10 ТЗ и `limits-audit.md`:
  * 36 — URL после прежнего 4k-среза находится и доступен для source fetch;
  * 37 — нужная часть документа после 8k достижима (section/offset/line_range
    + `full_source_pointer`, остаток догружается тем же инструментом);
  * 38 — большое окно → evidence реально больше (и без двойного резерва, C4);
  * 39 — маленькое/unknown окно → claim→source сохранён, URL/JSON не разрезаны,
    overflow решается retrieval'ом, причины наблюдаемы;
  * 30/31 — reuse того же claim без нового сетевого вызова; смена
    версии/даты/метрики, TTL и контрдоказательство инвалидируют;
  * 8 — поисковая выдача = только кандидаты (`snippet`), не `fetched`;
  * 9 — 403/404/timeout/пустая страница → честная деградация с причиной;
  * 10 — два источника с разными датами сохраняются и различаются;
  * 40 — медленный поиск → bounded terminal status (не вечное ожидание);
  * 44 — reuse существующих сервисов (тот же aggregator/extractor), ноль
    новых сетевых/DB-контуров в `source_reuse`;
  * 46 — числовые счётчики reuse (fetched/reuse/failed) вместо текста.

Фикстуры offline: сеть не используется, провайдеры подменены.
"""
import asyncio
import ast
import json
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from services import auto_budget
from services import model_capacity
from services import source_reuse
from services.tool_router import ToolContext, ToolDeps, ToolRouter
from services.web_content_extractor import (
    ExtractedDocument,
    WebContentExtractionFailedException,
    build_source_pointer,
    clip_at_boundary,
    content_terms,
    select_excerpt,
    split_sections,
)


# ── helpers ────────────────────────────────────────────────────────────────

def _router(*, search=None, extractor=None):
    return ToolRouter(ToolDeps(
        search=search if search is not None else MagicMock(),
        memory=MagicMock(), extractor=extractor))


def _ctx(query="q", *, budget=0, chat_id=-100):
    ctx = ToolContext(chat_id, query)
    ctx.evidence_budget_chars = budget
    return ctx


def _hits(count: int, *, target_position: int = 25, padding: int = 200):
    """Выдача поиска в реальном формате aggregator (`title\\nsnippet\\nurl`)."""
    blocks = []
    for index in range(count):
        url = (f"https://api-docs.example/news/news{1017 + index}/"
               if index == target_position else
               f"https://blog.example/page-{index}/")
        snippet = ("dummy snippet " + "x" * padding) if index % 2 else \
            ("фиiller " + "y" * padding)
        blocks.append(f"Заголовок {index}\n{snippet}\n{url}")
    return "\n\n".join(blocks)


class FakeExtractor:
    """Экстрактор с document-контрактом (без сети)."""

    def __init__(self, text="", *, links=(), published_at="",
                 published_source="", exc=None, short_content=False,
                 truncated_at_extraction=False, ceiling_reported=None):
        self.document = ExtractedDocument(
            text=text, provider="trafilatura", links=tuple(links),
            links_source="html" if links else "unavailable",
            published_at=published_at, published_at_source=published_source,
            short_content=short_content,
            total_chars=len(text),
            ceiling=ceiling_reported if ceiling_reported is not None else 0,
            truncated_at_extraction=truncated_at_extraction)
        self.exc = exc
        self.calls = []

    async def extract_document(self, url, *, ceiling=None):
        self.calls.append((url, ceiling))
        if self.exc is not None:
            raise self.exc
        return self.document


def _filler(chars: int, token: str = "текст ") -> str:
    unit = len(token)
    return token * max(1, chars // unit)


def _long_document(prefix_chars: int = 25_000, marker: str = "release 1017",
                   tail_chars: int = 20_000) -> str:
    """Документ с нужным разделом ПОСЛЕ ``prefix_chars`` и хвостом после него.

    Так проверяются обе стороны: раздел за 8k достижим, а остаток после
    выдержки реально существует и догружается offset'ом."""
    head = _filler(prefix_chars, "Обычный текст без нужного раздела. ")
    middle = ("\n\n# Обновления API\n\n"
              "Официальный changelog подтверждает " + marker +
              ": версия выпущена 17 октября.\n")
    tail = "\n\n# Приложение\n\n" + _filler(tail_chars)
    return head + middle + tail


# ── сценарий 36: URL после 4k-среза достижим ───────────────────────────────

class TestSearchCandidateIndex:
    def test_url_after_old_4k_cut_is_reachable(self):
        text = _hits(30, target_position=25)
        assert len(text) > 4000 and "news1017" not in text[:4000]
        ctx = _ctx("deepseek v4.1 flash release")
        router = _router(search=MagicMock(
            search=AsyncMock(return_value=text)))
        out = asyncio.run(
            router.dispatch("execute_web_search", {"query": "q"}, ctx))
        # Сценарий 36: URL, который прежний слепой срез 4k выкидывал, есть.
        assert "https://api-docs.example/news/news1042/" in out or \
            "https://api-docs.example/news/news1017/" in out
        assert "api-docs.example/news/news" in out
        record = ctx.evidence_limits[-1]
        assert record["tool"] == "execute_web_search"
        assert record["effective_limit"] > 0
        assert record["unit"] == "blocks"
        assert record["candidates_total"] == 30
        assert record["source_read_level"] == "snippet"
        for field in ("effective_limit", "limit_source", "used", "total",
                      "truncated", "why", "retrievable_remainder"):
            assert field in record

    def test_small_window_keeps_all_urls(self):
        text = _hits(30)
        router = _router(search=MagicMock(
            search=AsyncMock(return_value=text)))
        ctx = _ctx("q", budget=1200)
        out = asyncio.run(
            router.dispatch("execute_web_search", {"query": "q"}, ctx))
        record = ctx.evidence_limits[-1]
        assert record["limit_source"] == "call_budget"
        # Контракт §4.3: поиск имеет soft floor 4000 (индекс кандидатов должен
        # помещаться даже на малом окне), потолок — hard ceiling класса C.
        assert record["effective_limit"] == max(
            auto_budget.SEARCH_RESULT_SOFT_FLOOR, int(1200 * 1.25))
        assert record["truncated"] is True
        assert record["why"].startswith("over_window")
        # Ни один URL не разрезан посередине.
        for line in out.splitlines():
            if line.startswith("http"):
                assert line.strip().endswith("/")

    def test_compacted_index_keeps_all_urls_and_marks_truncation(self):
        from services.tool_result import classify_output
        text = "\n\n".join(
            f"Заголовок {i}\nсниппет " + "x" * 300 +
            f"\nhttps://blog.example/p{i}/" for i in range(30))
        ctx = _ctx("q", budget=1200)
        router = _router(search=MagicMock(
            search=AsyncMock(return_value=text)))
        out = asyncio.run(
            router.dispatch("execute_web_search", {"query": "q"}, ctx))
        record = ctx.evidence_limits[-1]
        assert record["candidates_total"] == 30
        assert record["candidates_kept"] == 30
        assert record["why"] == "over_window_snippets_compacted"
        assert record["retrievable_remainder"] > 0
        urls = [line for line in out.splitlines() if line.startswith("http")]
        assert len(urls) == 30 and all(url.endswith("/") for url in urls)
        # Честный сигнал усечения для существующего tool_result-конверта.
        assert out.strip().endswith("…")
        assert classify_output("execute_web_search", out)["truncated"] is True

    def test_big_window_allows_more_than_legacy_ceiling(self):
        """Сценарий 38 (часть): 4000 — не потолок при большом окне."""
        text = _hits(14, padding=500)
        assert len(text) > 4000
        ctx = _ctx("q")
        router = _router(search=MagicMock(
            search=AsyncMock(return_value=text)))
        out = asyncio.run(
            router.dispatch("execute_web_search", {"query": "q"}, ctx))
        record = ctx.evidence_limits[-1]
        assert record["effective_limit"] > 4000
        assert record["truncated"] is False
        assert record["used"] == len(text)
        assert record["candidates_total"] == 14

    def test_search_large_window_derived_from_model_not_fixed_16k_or_32k(self):
        window, source = model_capacity.resolve_evidence_window_tokens()
        assert window > 0 and source in (
            model_capacity.WINDOW_SOURCE_MAP,
            model_capacity.WINDOW_SOURCE_ENV,
            model_capacity.WINDOW_SOURCE_FALLBACK)
        resolved = auto_budget.resolve_evidence_tool_window("search")
        assert resolved.effective_limit not in (16000, 32000)
        assert resolved.source in ("window", "legacy")


# ── сценарий 37: section-aware fetch длинного документа ─────────────────────

class TestSectionAwareFetch:
    def test_section_after_8k_is_delivered_with_provenance(self):
        document = _long_document(prefix_chars=25_000)
        assert document.index("release 1017") > 8000
        extractor = FakeExtractor(document)
        router = _router(extractor=extractor)
        ctx = _ctx("что нового в release 1017 ", budget=2000)
        raw = asyncio.run(router.dispatch(
            "fetch_article", {"url": "https://api-docs.example/updates/",
                              "terms": ["release", "1017"]}, ctx))
        payload = json.loads(raw)
        assert payload["status"] == "ok"
        assert "release 1017" in payload["markdown"]
        assert payload["selected_by"] in ("terms", "offset")
        assert payload["line_range"][0] > 1
        assert payload["chars"] == payload["excerpt_chars"] < payload["total_chars"]
        pointer = payload["full_source_pointer"]
        assert pointer["tool"] == "fetch_article"
        assert pointer["total_chars"] == payload["total_chars"]
        assert pointer["offset"] > 8000            # дальше старого 8k-среза
        assert payload["remainder_chars"] > 0
        assert payload["read_level"] == "selected"
        # Извлечение идёт до ceiling'а класса C, а не до 8000.
        assert extractor.calls[0][1] == auto_budget.ARTICLE_EXTRACT_CEILING_DEFAULT

    def test_remainder_retrievable_by_same_tool(self):
        document = _long_document(prefix_chars=25_000)
        extractor = FakeExtractor(document)
        router = _router(extractor=extractor)
        ctx = _ctx("q", budget=2000)
        first = json.loads(asyncio.run(router.dispatch(
            "fetch_article", {"url": "https://a.example/doc",
                              "terms": ["release"]}, ctx)))
        offset = first["full_source_pointer"]["offset"]
        second = json.loads(asyncio.run(router.dispatch(
            "fetch_article", {"url": "https://a.example/doc",
                              "offset": offset}, ctx)))
        assert second["status"] == "ok"
        assert second["selected_by"] == "offset"
        assert second["markdown"] != first["markdown"]
        # Догрузка продвигает указатель вперёд, остаток уменьшается.
        assert second["full_source_pointer"]["offset"] > offset
        assert second["remainder_chars"] < first["remainder_chars"]

    def test_sections_listed_with_line_ranges(self):
        document = _long_document(prefix_chars=10_000)
        sections = split_sections(document)
        headings = [item["heading"] for item in sections]
        assert "Обновления API" in headings and "Приложение" in headings
        for item in sections:
            assert item["start_line"] >= 1
            assert item["end_line"] >= item["start_line"]
            assert item["chars"] > 0
        excerpt = select_excerpt(document, budget_chars=800,
                                 section="Обновления API")
        assert "release 1017" in excerpt.text
        assert excerpt.remainder_chars > 0
        assert excerpt.line_range[0] >= 1

    def test_links_are_kept_as_structure_not_lost(self):
        document = _long_document(prefix_chars=1000)
        extractor = FakeExtractor(
            document, links=("https://api-docs.example/updates/",))
        router = _router(extractor=extractor)
        payload = json.loads(asyncio.run(router.dispatch(
            "fetch_article", {"url": "https://a.example/doc", "terms": []},
            _ctx("q"))))
        assert payload["links"] == ["https://api-docs.example/updates/"]
        assert payload["links_source"] == "html"


# ── сценарий 38/39: окно, C4, сохранение claim→source ──────────────────────

class TestDynamicWindow:
    def test_no_double_output_reserve(self, monkeypatch):
        """C4: tool-бюджет приходит уже без output reserve — второй раз его
        вычитать нельзя. Проверяем, что лимит инструмента не зависит от
        резерва вывода и равен ``budget × 1.25``."""
        window = auto_budget.resolve_evidence_tool_window(
            "article", call_budget_chars=8000)
        assert window.source == "call_budget"
        assert window.effective_limit == int(8000 * 1.25)
        # Никакого `- 512` (двойной резерв) в вычислении.
        assert window.effective_limit == 10000
        fields = window.as_event_fields()
        assert fields["budget_chars"] == 8000
        assert "output_reserve" not in fields

    def test_window_honours_hard_ceiling(self):
        window = auto_budget.resolve_evidence_tool_window(
            "search", call_budget_chars=10_000_000)
        assert window.effective_limit <= window.hard_ceiling

    def test_turn_level_avalanche_guard(self):
        """Суммарные tool-результаты хода ограничены долей окна."""
        window_tokens, _ = model_capacity.resolve_evidence_window_tokens()
        window_chars = model_capacity.chars_for_tokens(window_tokens)
        budget = int(window_chars * auto_budget.TOOL_EVIDENCE_TURN_SHARE_DEFAULT)
        first = auto_budget.resolve_evidence_tool_window(
            "article", turn_spent_chars=0)
        second = auto_budget.resolve_evidence_tool_window(
            "article", turn_spent_chars=budget)
        assert first.turn_capped is False
        assert second.turn_capped is True
        assert second.effective_limit < first.effective_limit
        assert second.effective_limit >= second.floor
        # Через контекст хода: после большого источника следующий урезан.
        ctx = _ctx("q")
        ctx.evidence_limits = [{"tool": "fetch_article", "used": budget}]
        router = _router(extractor=FakeExtractor(_long_document(2000)))
        payload = json.loads(asyncio.run(router.dispatch(
            "fetch_article", {"url": "https://a.example/x"}, ctx)))
        assert payload["status"] == "ok"
        assert ctx.evidence_limits[-1]["turn_capped"] is True

    def test_dynamic_off_keeps_legacy_behaviour(self, monkeypatch):
        monkeypatch.setattr(
            type(auto_budget.settings), "EVIDENCE_WINDOW_DYNAMIC_ENABLED",
            False, raising=False)
        window = auto_budget.resolve_evidence_tool_window(
            "search", call_budget_chars=50_000)
        assert window.source == "legacy"
        assert window.effective_limit == auto_budget.LEGACY_SEARCH_MAX_SYMBOLS

    def test_unknown_window_is_marked_and_conservative(self, monkeypatch):
        model_capacity._WINDOW_CACHE.clear()
        window = auto_budget.resolve_evidence_tool_window(
            "article", model="totally-unknown-model-xyz")
        assert window.source == "window"
        assert window.window_source in (
            model_capacity.WINDOW_SOURCE_FALLBACK,
            model_capacity.WINDOW_SOURCE_MAP,
            model_capacity.WINDOW_SOURCE_ENV)
        if window.window_source == model_capacity.WINDOW_SOURCE_FALLBACK:
            assert window.window_tokens == 16384
        model_capacity._WINDOW_CACHE.clear()

    def test_small_window_keeps_claim_source_and_urls(self):
        """Сценарий 39: overflow решается retrieval'ом, пара claim→source жива."""
        document = _long_document(prefix_chars=20_000)
        extractor = FakeExtractor(document)
        router = _router(extractor=extractor)
        ctx = _ctx("release 1017", budget=900)
        payload = json.loads(asyncio.run(router.dispatch(
            "fetch_article", {"url": "https://a.example/doc",
                              "claim": {"entity": "deepseek v4.1 flash",
                                        "relation": "version",
                                        "version": "1017"}}, ctx)))
        assert payload["status"] == "ok"
        assert payload["chars"] <= int(900 * 1.25) + 40
        claim = source_reuse.claim_key("deepseek v4.1 flash", "version", "1017")
        link = source_reuse.link_claim_source(claim, payload)
        assert link["claim_key"] == claim.key()
        assert link["read_level"] in ("selected", "parsed")
        coverage = source_reuse.build_coverage([claim], [link])
        assert coverage["coverage_ratio"] == 1.0
        # Указатель ведёт на полный источник того же URL.
        assert payload["full_source_pointer"]["url"] == "https://a.example/doc"

    def test_json_payload_never_sliced(self):
        """Обрезка не режет JSON/URL: `_truncate` сохраняет валидный JSON."""
        from services.tool_router import _truncate
        payload = json.dumps({"status": "ok", "url": "https://a.example/x",
                              "chars": 1}, ensure_ascii=False)
        assert _truncate(payload, 10) == payload
        clipped = _truncate("слово https://a.example/long/path?x=1 и текст", 25)
        assert "https://" not in clipped or clipped.endswith("path?x=1")

    def test_clip_at_boundary_keeps_url_whole(self):
        text = "текст " * 40 + "https://api-docs.example/updates/"
        limit = text.index("https://") + 10
        clipped = clip_at_boundary(text, limit)
        assert "https://api-docs.example/updates/" not in clipped
        assert clipped.strip().endswith("текст")

    def test_content_terms_extracts_entity(self):
        terms = content_terms("deepseek v4.1 flash release 1017")
        assert any(term.startswith("deepse") for term in terms)
        assert "flash" in terms


class TestReaderDocumentContract:
    """web_content_extractor: reader отдаёт документ, ограничение — доставка."""

    def test_short_valid_page_is_document_not_failure(self, monkeypatch):
        from services.web_content_extractor import WebContentExtractor

        extractor = WebContentExtractor(tavily_api_key="", exa_api_key="")

        async def short_level(url):
            return "Версия 1017 выпущена. Короткий changelog.", (), "", ""

        monkeypatch.setattr(extractor, "_extract_trafilatura", short_level)
        document = asyncio.run(extractor.extract_document("https://a.example/x"))
        assert document.short_content is True
        assert document.text.startswith("Версия 1017")
        assert document.provider == "trafilatura"

    def test_extraction_ceiling_is_honest(self, monkeypatch):
        """Review fix: `total_chars` — РЕАЛЬНЫЙ объём, а не доставленное.

        Иначе вызывающий видел «total == доставлено» и не мог отличить
        «документ кончился» от «обрезано при извлечении»."""
        from services.web_content_extractor import WebContentExtractor

        extractor = WebContentExtractor(tavily_api_key="", exa_api_key="")

        async def long_level(url):
            return "текст " * 5000, (), "", ""

        monkeypatch.setattr(extractor, "_extract_trafilatura", long_level)
        document = asyncio.run(
            extractor.extract_document("https://a.example/x", ceiling=1000))
        assert document.total_chars == len("текст " * 5000)   # 30 000, не 1000
        assert len(document.text) == 1000
        assert document.truncated_at_extraction is True
        assert document.ceiling == 1000

    def test_extraction_ceiling_keeps_total_and_remainder_honest(self,
                                                                 monkeypatch):
        """Review fix: остаток после extraction-ceiling'а не притворяется нулём."""
        document = "р" * 30_000
        extractor = FakeExtractor(document)

        async def _ceiling(url, *, ceiling=None):
            from services.web_content_extractor import ExtractedDocument
            # Экстрактор честно упёрся в собственный потолок 5000 (меньше
            # реального объёма страницы) — доставлено 5000 из 30 000.
            return ExtractedDocument(url=url, text=document[:5000],
                                     total_chars=len(document), ceiling=5000,
                                     truncated_at_extraction=True)

        extractor.extract_document = _ceiling
        router = _router(extractor=extractor)
        ctx = _ctx("q")
        payload = json.loads(asyncio.run(router.dispatch(
            "fetch_article", {"url": "https://a.example/doc"}, ctx)))
        assert payload["status"] == "ok"
        assert payload["total_chars"] == 30_000
        assert payload["chars"] == len(payload["markdown"]) < 30_000
        assert payload["remainder_chars"] == 30_000 - payload["chars"]
        # Добрать остаток тем же инструментом нельзя — потолок извлечения.
        assert payload["remainder_retrievable_chars"] == 0
        assert payload["truncated_at_extraction"] is True
        record = ctx.evidence_limits[-1]
        assert record["why"] == "extraction_ceiling"
        assert record["retrievable_remainder"] == 0

    def test_evidence_window_kill_switch_is_registered_in_settings(self):
        """Review fix: `EVIDENCE_WINDOW_DYNAMIC_ENABLED` — реальный флаг.

        Рубильник должен существовать как env-контролируемый ClassVar (не
        dataclass-поле: каталог настроек не растёт) и управлять резолвом."""
        import dataclasses

        from config.settings import Settings, settings

        names = [f.name for f in dataclasses.fields(Settings)]
        assert "EVIDENCE_WINDOW_DYNAMIC_ENABLED" not in names   # каталог-Δ = 0
        assert getattr(settings, "EVIDENCE_WINDOW_DYNAMIC_ENABLED") is True
        assert model_capacity.evidence_window_dynamic_enabled() is True

    def test_links_and_published_at_from_html(self):
        from services.web_content_extractor import (
            _extract_links,
            _extract_published_at,
        )

        html = (
            '<html><head><meta property="article:published_time" '
            'content="2026-10-17T10:00:00Z"></head><body>'
            '<a href="/news/">Официальные новости</a>'
            '<a href="mailto:x@y.z">mail</a>'
            '<a href="javascript:void(0)">js</a>'
            '<a href="https://other.example/doc">doc</a></body></html>')
        links = _extract_links(html, "https://api-docs.example/updates/")
        assert "https://api-docs.example/news/" in links
        assert "https://other.example/doc" in links
        assert all(link.startswith("http") for link in links)
        published, source = _extract_published_at(html)
        assert published == "2026-10-17T10:00:00Z" and source == "meta"

    def test_reader_legacy_extract_still_truncates_for_preview(self):
        from services.web_content_extractor import (
            ExtractedDocument,
            WebContentExtractor,
        )

        extractor = WebContentExtractor(tavily_api_key="", exa_api_key="")

        async def fake_document(url, *, ceiling=None):
            return ExtractedDocument(url=url, text="ю" * 500, total_chars=500)

        extractor.extract_document = fake_document
        assert asyncio.run(extractor.extract("https://a.example/x", 60)) == \
            "ю" * 60


# ── сценарий 8/9/10: честный статус чтения и деградация ────────────────────

class TestHonestStatus:
    def test_search_is_snippet_not_fetched(self):
        ctx = _ctx("q")
        router = _router(search=MagicMock(
            search=AsyncMock(return_value=_hits(3))))
        asyncio.run(router.dispatch("execute_web_search", {"query": "q"}, ctx))
        record = ctx.evidence_limits[-1]
        assert record["source_read_level"] == "snippet"
        assert source_reuse.delivery_state(
            source_fetched=False, delivered_chars=0) == "not_fetched"
        assert source_reuse.delivery_state(
            source_fetched=True, delivered_chars=0) == "fetched_not_delivered"
        assert source_reuse.delivery_state(
            source_fetched=True, delivered_chars=100) == "delivered"
        assert source_reuse.delivery_state(
            source_fetched=True, delivered_chars=100,
            reused=True) == "verified_reuse"

    def test_short_valid_page_is_not_unavailable(self):
        extractor = FakeExtractor("Версия 1017 выпущена.", short_content=True)
        router = _router(extractor=extractor)
        payload = json.loads(asyncio.run(router.dispatch(
            "fetch_article", {"url": "https://a.example/changelog"}, _ctx())))
        assert payload["status"] == "ok"
        assert payload["short_content"] is True
        assert payload["markdown"].startswith("Версия 1017")

    def test_fetch_failure_is_honest(self):
        extractor = FakeExtractor(
            exc=WebContentExtractionFailedException("all failed"))
        router = _router(extractor=extractor)
        payload = json.loads(asyncio.run(router.dispatch(
            "fetch_article", {"url": "https://a.example/missing"}, _ctx())))
        assert payload["status"] == "error"
        assert payload["error"] == "extract_failed"
        assert payload["reason"] == "source_unavailable"
        assert "source_fetched" not in payload
        assert "не существует" not in json.dumps(payload, ensure_ascii=False)

    def test_two_sources_keep_distinct_publication_dates(self):
        first = FakeExtractor(_long_document(1000, "release 1017"),
                              published_at="2026-10-17T00:00:00Z",
                              published_source="meta")
        second = FakeExtractor(_long_document(1000, "release 1018"),
                               published_at="2026-10-18T00:00:00Z",
                               published_source="time")
        p1 = json.loads(asyncio.run(_router(extractor=first).dispatch(
            "fetch_article", {"url": "https://a.example/1"}, _ctx())))
        p2 = json.loads(asyncio.run(_router(extractor=second).dispatch(
            "fetch_article", {"url": "https://b.example/2"}, _ctx())))
        assert p1["published_at"] != p2["published_at"]
        assert p1["published_at_source"] == "meta"
        assert p2["published_at_source"] == "time"
        assert p1["source_id"] != p2["source_id"]


# ── сценарий 40: медленный поиск — bounded terminal status ─────────────────

class TestBoundedSearch:
    def test_hung_search_returns_terminal_status(self, monkeypatch):
        async def slow(query, max_symbols):
            await asyncio.sleep(5)
            return "поздно"

        import time

        import services.tool_router as tool_router_mod
        monkeypatch.setattr(tool_router_mod, "_SEARCH_TOOL_TIMEOUT", 0.15)
        router = _router(search=MagicMock(search=slow))
        ctx = _ctx("q")
        started = time.monotonic()
        raw = asyncio.run(
            router.dispatch("execute_web_search", {"query": "q"}, ctx))
        elapsed = time.monotonic() - started
        assert elapsed < 3.0
        assert raw.startswith("ОШИБКА execute_web_search")
        assert "timeout" in raw
        # Терминальный статус не оставляет «вечного» конверта лимитов.
        assert ctx.evidence_limits == []


# ── сценарий 30/31/46: claim-bound reuse ───────────────────────────────────

@pytest.fixture(autouse=True)
def _clean_reuse():
    source_reuse.clear()
    source_reuse.reset_stats()
    yield
    source_reuse.clear()
    source_reuse.reset_stats()


class TestSourceReuse:
    def test_same_claim_reuses_source_without_new_call(self):
        extractor = FakeExtractor(_long_document(2000, "release 1017"))
        router = _router(extractor=extractor)
        claim = {"entity": "deepseek v4.1 flash", "relation": "version",
                 "version": "1017"}
        args = {"url": "https://a.example/updates/", "claim": claim}
        first = json.loads(asyncio.run(
            router.dispatch("fetch_article", dict(args), _ctx())))
        assert first["status"] == "ok" and not first.get("reused")
        second = json.loads(asyncio.run(
            router.dispatch("fetch_article", dict(args), _ctx())))
        assert second["reused"] is True
        assert second["network_calls"] == 0
        assert second["reuse"].startswith("reuse: ")
        assert second["source_id"] == first["source_id"]
        # Экстрактор вызывался ровно один раз — второго сетевого чтения нет.
        assert len(extractor.calls) == 1

    def test_changed_version_does_new_fetch(self):
        extractor = FakeExtractor(_long_document(2000, "release 1018"))
        router = _router(extractor=extractor)
        asyncio.run(router.dispatch("fetch_article", {
            "url": "https://a.example/updates/",
            "claim": {"entity": "deepseek v4.1 flash", "relation": "version",
                      "version": "1017"}}, _ctx()))
        result = json.loads(asyncio.run(router.dispatch("fetch_article", {
            "url": "https://a.example/updates/",
            "claim": {"entity": "deepseek v4.1 flash", "relation": "version",
                      "version": "1018"}}, _ctx())))
        assert not result.get("reused")
        assert len(extractor.calls) == 2

    def test_metric_and_date_are_part_of_key(self):
        base = source_reuse.claim_key("rtx 5090", "spec", metric="vram_gb")
        other_metric = source_reuse.claim_key("rtx 5090", "spec",
                                             metric="tdp_w")
        other_date = source_reuse.claim_key("rtx 5090", "spec",
                                           date="2026-10-17")
        assert base.key() != other_metric.key()
        assert base.key() != other_date.key()
        assert base.key() == source_reuse.claim_key(
            "RTX   5090", "spec", metric="vram_gb").key()

    def test_counter_evidence_blocks_reuse(self):
        claim = source_reuse.claim_key("deepseek v4.1 flash", "version", "1017")
        source_reuse.store(claim, url="https://a.example/x", source_id="abc",
                           snippet="release 1017", read_level="parsed")
        assert source_reuse.lookup(claim) is not None
        assert source_reuse.mark_contested(claim) is True
        assert source_reuse.lookup(claim) is None
        assert source_reuse.stats()["contested_hits"] >= 1

    def test_ttl_expiry_and_bypass(self):
        claim = source_reuse.claim_key("btc", "price", metric="usd")
        source_reuse.store(claim, url="https://a.example/p", source_id="p1",
                           snippet="курс", read_level="parsed")
        assert source_reuse.lookup(claim) is not None
        # TTL live_market = 900 c: через 1000 c запись истекла.
        import time as _time
        future = _time.time() + 1000
        assert source_reuse.lookup(claim, now=future) is None
        assert source_reuse.stats()["expired"] >= 1
        # bypass («обнови/проверь заново») → miss даже при свежей записи.
        source_reuse.store(claim, url="https://a.example/p", source_id="p2",
                           snippet="курс", read_level="parsed")
        assert source_reuse.lookup(claim, bypass=True) is None

    def test_chat_isolation(self):
        claim = source_reuse.claim_key("локальный факт", "exists")
        source_reuse.store(claim, url="https://private.example/x",
                           source_id="p", snippet="секрет", read_level="parsed",
                           scope="chat", chat_id=111)
        assert source_reuse.lookup(claim, scope="chat", chat_id=111) is not None
        assert source_reuse.lookup(claim, scope="chat", chat_id=222) is None
        # Публичный источник переиспользуется на основании самого источника.
        public = source_reuse.claim_key("deepseek v4.1 flash", "version", "1017")
        source_reuse.store(public, url="https://api-docs.example/updates/",
                           source_id="pub", snippet="release", read_level="parsed")
        assert source_reuse.lookup(public, chat_id=999) is not None

    def test_fetched_is_not_verified_reuse_until_delivered(self):
        claim = source_reuse.claim_key("deepseek v4.1 flash", "version", "1017")
        record = source_reuse.store(
            claim, url="https://a.example/x", source_id="abc",
            snippet="release 1017", read_level="parsed")
        assert record.verified_reuse is False
        assert source_reuse.delivery_state(
            source_fetched=True, delivered_chars=0,
            reused=True) == "fetched_not_delivered"
        source_reuse.record_delivery(claim, 800)
        assert source_reuse.lookup(claim).verified_reuse is True
        assert source_reuse.stats()["delivered"] == 1

    def test_snippet_candidate_is_not_read_source(self):
        claim = source_reuse.claim_key("deepseek v4.1 flash", "version", "1017")
        source_reuse.store(claim, url="https://a.example/x", source_id="abc",
                           snippet="сниппет", read_level="snippet")
        assert source_reuse.lookup(claim) is None

    def test_search_skips_network_when_claim_reused(self):
        search = MagicMock(search=AsyncMock(return_value=_hits(3)))
        router = _router(search=search)
        claim = source_reuse.claim_key("deepseek v4.1 flash", "version", "1017")
        source_reuse.store(claim, url="https://api-docs.example/updates/",
                           source_id="pub", snippet="release 1017",
                           read_level="parsed")
        ctx = _ctx("что нового в релизе")
        ctx.claim_keys = [claim]
        out = asyncio.run(router.dispatch("execute_web_search",
                                          {"query": "q"}, ctx))
        assert "(reuse)" in out and "reuse: " in out
        search.search.assert_not_called()
        assert ctx.evidence_limits[-1]["network_calls"] == 0
        assert ctx.evidence_limits[-1]["reused"] is True

    def test_reuse_ttl_by_claim_class(self):
        assert source_reuse.ttl_seconds("live_market") == 900
        assert source_reuse.ttl_seconds("release_news") == 6 * 3600
        assert source_reuse.ttl_seconds("spec_parameters") == 7 * 86400
        assert source_reuse.ttl_seconds("official_docs") == 14 * 86400
        assert source_reuse.ttl_seconds("historical_fact") == 30 * 86400
        assert source_reuse.claim_class_for("price") == "live_market"
        assert source_reuse.claim_class_for("version") == "release_news"
        assert source_reuse.claim_class_for("spec") == "spec_parameters"

    def test_reuse_kill_switch(self, monkeypatch):
        monkeypatch.setattr(type(source_reuse.settings),
                            "EVIDENCE_REUSE_ENABLED", False, raising=False)
        claim = source_reuse.claim_key("deepseek v4.1 flash", "version", "1017")
        assert source_reuse.store(claim, url="https://a.example/x",
                                  source_id="abc", snippet="text",
                                  read_level="parsed") is None
        assert source_reuse.lookup(claim) is None

    def test_lru_is_bounded(self, monkeypatch):
        monkeypatch.setattr(source_reuse, "_max_entries", lambda: 2)
        keys = [source_reuse.claim_key("e", "version", str(i)) for i in range(4)]
        for key in keys:
            source_reuse.store(key, url="https://a.example/x",
                               source_id=key.key(), snippet="s",
                               read_level="parsed")
        assert source_reuse.stats()["entries"] == 2
        assert source_reuse.lookup(keys[0]) is None
        assert source_reuse.lookup(keys[-1]) is not None

    def test_restart_limitation_is_explicit(self):
        claim = source_reuse.claim_key("deepseek v4.1 flash", "version", "1017")
        source_reuse.store(claim, url="https://a.example/x", source_id="abc",
                           snippet="text", read_level="parsed")
        source_reuse.clear()          # рестарт процесса
        assert source_reuse.lookup(claim) is None


# ── сценарий 44: reuse существующих сервисов, без новых контуров ───────────

class TestReuseOfExistingServices:
    def test_router_uses_injected_search_and_extractor(self):
        search = MagicMock(search=AsyncMock(return_value=_hits(2)))
        extractor = FakeExtractor(_long_document(500))
        router = _router(search=search, extractor=extractor)
        asyncio.run(router.dispatch("execute_web_search", {"query": "q"},
                                    _ctx()))
        asyncio.run(router.dispatch("fetch_article",
                                    {"url": "https://a.example/x"}, _ctx()))
        assert search.search.await_count == 1
        assert len(extractor.calls) == 1

    def test_source_reuse_has_no_network_or_db_imports(self):
        import services.source_reuse as module
        path = Path(module.__file__)
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imported: set[str] = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imported.update(alias.name.split(".")[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imported.add(node.module.split(".")[0])
        assert not imported & {"httpx", "aiohttp", "requests", "aiosqlite",
                               "sqlite3", "services.database"}

    def test_web_content_extractor_has_single_fetch_contour(self):
        import services.web_content_extractor as module
        source = Path(module.__file__).read_text(encoding="utf-8")
        # Единственный fetch-контур: safe_fetch + ленивый httpx-клиент.
        assert "safe_fetch.SafeFetcher" in source
        assert "client.get(" not in source.replace("legacy = await client.get(", "")


# ── сценарий 46: числовые счётчики, а не текст ─────────────────────────────

class TestCounters:
    def test_stats_have_numeric_axes(self):
        claim = source_reuse.claim_key("deepseek v4.1 flash", "version", "1017")
        source_reuse.store(claim, url="https://a.example/x", source_id="abc",
                           snippet="text", read_level="parsed")
        source_reuse.lookup(claim)
        source_reuse.lookup(source_reuse.claim_key("other", "exists"))
        stats = source_reuse.stats()
        for axis in ("lookups", "hits", "misses", "stored", "entries",
                     "expired", "contested_hits", "delivered", "errors"):
            assert axis in stats and isinstance(stats[axis], int)
        assert stats["hits"] == 1 and stats["misses"] == 1
        assert stats["errors"] == 0
        assert stats["enabled"] in (True, False)

    def test_coverage_reports_missing_claims(self):
        covered = source_reuse.claim_key("deepseek v4.1 flash", "version", "1017")
        missing = source_reuse.claim_key("deepseek v4.1 flash", "price",
                                        metric="usd")
        links = [{"claim_key": covered.key(), "source_id": "abc",
                  "read_level": "selected", "url": "https://a.example/x"}]
        coverage = source_reuse.build_coverage([covered, missing], links)
        assert coverage["covered"] == [covered.key()]
        assert coverage["missing"] == [missing.key()]
        assert coverage["coverage_ratio"] == 0.5


# ── единый канон claim-key с policy-слоем (§3.2) ───────────────────────────

class TestSingleClaimKeyCanon:
    def test_matches_policy_claim_key_class(self):
        pytest.importorskip("services.evidence_policy")
        from services.evidence_policy import ClaimKey as PolicyClaimKey

        mine = source_reuse.claim_key("DeepSeek  V4.1 Flash", "version",
                                      "1017")
        theirs = PolicyClaimKey(entity="DeepSeek  V4.1 Flash",
                               relation="version", version="1017")
        assert mine.key() == theirs.key()
        # Локальный класс делегирует тот же дайджест (второй канон запрещён).
        local = source_reuse.ClaimKey(entity="DeepSeek  V4.1 Flash",
                                      relation="version", version="1017")
        assert local.key() == theirs.key()

    def test_foreign_claim_key_passes_through(self):
        pytest.importorskip("services.evidence_policy")
        from services.evidence_policy import ClaimKey as PolicyClaimKey

        theirs = PolicyClaimKey(entity="deepseek v4.1 flash",
                               relation="version", version="1017")
        assert source_reuse.claim_key_from_mapping(theirs) is theirs

    def test_policy_claim_keys_are_accepted_by_cache(self):
        pytest.importorskip("services.evidence_policy")
        from services.evidence_policy import ClaimKey as PolicyClaimKey

        theirs = PolicyClaimKey(entity="deepseek v4.1 flash",
                               relation="version", version="1017")
        source_reuse.store(theirs, url="https://a.example/x", source_id="abc",
                           snippet="release 1017", read_level="parsed")
        assert source_reuse.lookup(theirs) is not None
        mine = source_reuse.claim_key("deepseek v4.1 flash", "version", "1017")
        assert source_reuse.lookup(mine) is not None


class TestL1WindowLineBudget:
    """Волна 4: кап строки L1-окна выводится из реального бюджета (§1.5).

    Корневая причина дефекта «L1 не видит claim»: фиксированные 200 символов
    резали длинное сообщение, и версия/цена/дата не доезжали до планера,
    поэтому optional-поле external_claims почти не заполнялось."""

    def test_short_window_gets_longer_lines(self):
        from services import direct_l1 as l1

        one = [{"author_name": "A", "text": "x" * 900, "id": 1}]
        assert l1.window_line_chars(one) > l1.L1_WINDOW_LINE_CHARS
        # Потолок класса C соблюдается даже для одного огромного сообщения.
        assert l1.window_line_chars(one) <= l1.L1_WINDOW_LINE_CHARS_MAX

    def test_full_window_keeps_legacy_floor(self):
        from services import direct_l1 as l1

        rows = [{"author_name": "A", "text": "y" * 400} for _ in range(20)]
        assert l1.window_line_chars(rows) == l1.L1_WINDOW_LINE_CHARS

    def test_claim_after_old_200_chars_reaches_planner(self):
        from services import direct_l1 as l1

        body = "k" * 260 + " версия 1017 вышла"
        ctx = l1.build_l1_context(
            query="q", window=[{"author_name": "A", "text": body, "id": 1}],
            speaker="A")
        assert "версия 1017 вышла" in ctx

    def test_total_l1_budget_still_enforced(self):
        from services import direct_l1 as l1

        rows = [{"author_name": f"A{i}", "text": "z" * 5000} for i in range(20)]
        ctx = l1.build_l1_context(query="вопрос", window=rows, speaker="A",
                                  budget_tokens=400)
        # Потолок одной строки не отменяет общий бюджет пакета.
        assert len(ctx) < 200 * 400 // 4 + 2000
