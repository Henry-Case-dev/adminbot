# services/web_content_extractor.py (НОВЫЙ)
"""Epic 38 — WebContentExtractor (R38-3, D134/D136, Section 47.4).

Каскад: trafilatura → Tavily /extract → Exa /contents (прецедент
SearchAggregator: ленивый httpx.AsyncClient, skip уровня при пустом ключе,
ретраев внутри уровней НЕТ). Все уровни упали → WebContentExtractionFailedException
→ пул 5.7 (WEB_ERROR_PHRASES) в handlers/web.py.

ASAP-EVIDENCE-ROUTING-01 v3 (§3 Retrieve/§4.4 Preserve, `limits-audit.md` №2/4/5/6):
reader отдаёт ДОКУМЕНТ (`extract_document`) без среза доставки — ограничение
размера делает `tool_router._fetch_article` (section selection по терминам
claim, `offset`/`section`, `line_range`, `full_source_pointer`). Короткая
валидная страница помечается `short_content`, а не превращается в «источник
недоступен»; ссылки первоисточника и дата публикации извлекаются из того же
HTML отдельными полями. `extract(url, max_symbols)` сохранён как preview-путь
(`web_summarizer_service`)."""
import asyncio
import logging
import re
import time
from dataclasses import dataclass
from urllib.parse import urljoin, urlsplit

import httpx

from config.settings import settings
from services import hot_config as hot
from services import mca_gates
from services import safe_fetch

try:
    import trafilatura
except ImportError:  # pragma: no cover — зависимость в requirements.txt
    trafilatura = None

logger = logging.getLogger(__name__)

TAVILY_EXTRACT_URL = "https://api.tavily.com/extract"
EXA_CONTENTS_URL = "https://api.exa.ai/contents"

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
)
_FETCH_TIMEOUT = 10.0   # trafilatura: скачивание HTML (ТЗ)
_API_TIMEOUT = 15.0     # Tavily / Exa (ТЗ)
#: ASAP-EVIDENCE-ROUTING-01 v3 (P0-b, `limits-audit.md` №6): порог «короткого
#: контента» решает ТОЛЬКО вопрос «пробовать ли следующий уровень каскада».
#: Это не отказ уровня: короткий официальный changelog/release-notes
#: (120 символов) — валидная страница со статусом ok + `short_content=true`,
#: а не ложный «источник недоступен».
_MIN_CONTENT_CHARS = 150

#: Ссылки первоисточника — только структурой (не в тексте), ограниченно и
#: безопасно (`limits-audit.md` №5, `include_links` честно).
_MAX_LINKS = 40
_LINK_RE = re.compile(r"""<a\b[^>]*?\bhref\s*=\s*["']([^"'#]+)["']""",
                      re.IGNORECASE)
_PUBLISHED_META_RES = (
    re.compile(
        r"""<meta[^>]+(?:property|name)\s*=\s*["'](?:article:published_time|"""
        r"""og:article:published_time|datePublished|pubdate|publish-date|"""
        r"""date)["'][^>]*?content\s*=\s*["']([^"']+)["']""", re.IGNORECASE),
    re.compile(
        r"""<meta[^>]+content\s*=\s*["']([^"']+)["'][^>]*?(?:property|name)"""
        r"""\s*=\s*["'](?:article:published_time|datePublished|pubdate|"""
        r"""publish-date)["']""", re.IGNORECASE),
    re.compile(r"""<time[^>]+datetime\s*=\s*["']([^"']+)["']""",
               re.IGNORECASE),
)

#: коды SafeFetcher, при которых облачные фолбеки запрещены (опасное назначение).
_POLICY_BLOCK_CODES = frozenset({
    "scheme_not_allowed", "credentials_in_url", "invalid_url",
    "destination_blocked", "metadata_endpoint_blocked", "redirect_blocked",
    "too_many_redirects",
})


class WebContentExtractionFailedException(Exception):
    """Все уровни каскада провалились/пусто. → пул 5.7 (WEB_ERROR_PHRASES).

    MCA-11 (ADR-1028-13 D1/T-4948, M-MCA02-3): аддитивный ``safe_error`` —
    последняя ``SafeFetchError`` (code/stage/reason/retryable) для маппинга в
    ToolResult без второго error-контракта; message не меняется."""

    def __init__(self, message: str = "", *, safe_error=None) -> None:
        super().__init__(message)
        self.safe_error = safe_error


# ── ASAP-EVIDENCE-ROUTING-01 v3 (§3 Retrieve / §4.4): документ и выдержки ───


@dataclass(frozen=True)
class ExtractedDocument:
    """Прочитанный документ целиком (БЕЗ среза доставки).

    Reader больше не режет текст до 8000: он отдаёт документ до технического
    ceiling'а (класс C, `auto_budget.article_extract_ceiling`), а ограничение
    доставки делает вызывающий (`fetch_article` → section selection).
    ``short_content`` — страница короче `_MIN_CONTENT_CHARS`, но валидная."""

    url: str = ""
    text: str = ""
    provider: str = ""
    short_content: bool = False
    links: tuple[str, ...] = ()
    links_source: str = "unavailable"     # html | unavailable
    published_at: str = ""
    published_at_source: str = ""          # meta | time | ""
    #: РЕАЛЬНЫЙ объём извлечённого текста ДО обрезки ceiling'ом: `text` может
    #: быть короче, если `truncated_at_extraction` (тогда остаток потерян на
    #: извлечении, и `total_chars` не должен притворяться доставленным).
    total_chars: int = 0
    ceiling: int = 0
    truncated_at_extraction: bool = False
    levels_tried: tuple[str, ...] = ()


@dataclass(frozen=True)
class Excerpt:
    """Выбранная часть документа + provenance (указатель на полный источник)."""

    text: str = ""
    start: int = 0
    end: int = 0
    line_range: tuple[int, int] = (0, 0)
    total_chars: int = 0
    remainder_chars: int = 0
    selected_by: str = ""                 # whole | terms | section | offset
    sections: tuple[dict, ...] = ()
    truncated: bool = False


_HEADING_RE = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
_WORD_RE = re.compile(r"[\w\-]{3,}", re.UNICODE)
#: Токен URL: границы реза не должны попадать внутрь него (§4.4 Preserve).
_URL_TOKEN_RE = re.compile(r"https?://\S+")


def clip_at_boundary(text: str, limit: int) -> str:
    """Урезать строку по границе слова/токена, не разрывая URL.

    Последняя точка правды для «слепого реза нет»: сначала пробел, затем
    начало URL-токена; если текста без пробелов нет — срез неизбежен, но он
    не рвёт URL."""
    body = str(text or "")
    if limit <= 0 or len(body) <= limit:
        return body
    # 1) не рвать URL: срез внутри URL-токена → отступаем к началу токена.
    for match in _URL_TOKEN_RE.finditer(body):
        start, end = match.span()
        if start < limit < end:
            return body[:start].rstrip()
    cut = body[:limit]
    # 2) граница слова (пробел/перевод строки).
    boundary = max(cut.rfind(" "), cut.rfind("\t"), cut.rfind("\n"))
    if boundary >= max(16, int(limit * 0.6)):
        return cut[:boundary].rstrip()
    return cut.rstrip()


def content_terms(text: str, *, limit: int = 24) -> set[str]:
    """Содержательные термины текста (lower, стем-подобно: префикс 6)."""
    terms: set[str] = set()
    for word in _WORD_RE.findall(str(text or "").lower()):
        if len(word) < 3:
            continue
        terms.add(word[:6])
        if len(terms) >= limit:
            break
    return terms


def split_sections(text: str) -> tuple[dict, ...]:
    """Секции markdown-документа по заголовкам (line ranges — 1-based).

    Документ без заголовков → одна секция на весь текст (честно, не выдумка).
    Границы — всегда по строкам, поэтому выдержка никогда не рвёт строку/URL
    посередине."""
    body = str(text or "")
    if not body.strip():
        return ()
    lines = body.splitlines()
    sections: list[dict] = []
    current: dict | None = None
    for index, line in enumerate(lines, start=1):
        match = _HEADING_RE.match(line.strip())
        if match:
            if current is not None:
                current["end_line"] = index - 1
                current["chars"] = sum(
                    len(lines[n - 1]) + 1
                    for n in range(current["start_line"],
                                   current["end_line"] + 1))
                sections.append(current)
            current = {"heading": match.group(2).strip(),
                       "level": len(match.group(1)),
                       "start_line": index, "end_line": len(lines)}
        elif current is None:
            current = {"heading": "", "level": 0, "start_line": 1,
                       "end_line": len(lines)}
    if current is not None:
        current["end_line"] = len(lines)
        current["chars"] = sum(
            len(lines[n - 1]) + 1
            for n in range(current["start_line"], current["end_line"] + 1))
        sections.append(current)
    return tuple(sections)


def _slice_by_lines(text: str, start_line: int, count_chars: int
                    ) -> tuple[str, int, int, int]:
    """Взять строки начиная с ``start_line`` (1-based) в пределах символов.

    Возвращает ``(slice_text, start_offset, end_offset, end_line)``. Режем по
    границам строк — URL/JSON внутри строки не разрываются."""
    lines = str(text or "").splitlines(keepends=True)
    if not lines:
        return "", 0, 0, 0
    index = max(0, min(len(lines) - 1, int(start_line or 1) - 1))
    start_offset = sum(len(line) for line in lines[:index])
    taken: list[str] = []
    used = 0
    cursor = index
    while cursor < len(lines):
        line = lines[cursor]
        if taken and used + len(line) > count_chars:
            break
        taken.append(line)
        used += len(line)
        cursor += 1
        if used >= count_chars:
            break
    body = "".join(taken)
    if len(taken) == 1 and len(body) > count_chars:
        # Одна строка длиннее бюджета (минифицированный текст/код): режем по
        # границе слова/URL внутри строки, а не отдаём всё или рвём ссылку.
        body = clip_at_boundary(body, count_chars)
    return (body, start_offset, start_offset + len(body), cursor)


def select_excerpt(text: str, *, budget_chars: int, terms=(),
                   section: str | int | None = None,
                   offset: int | None = None) -> Excerpt:
    """Секционно-осознанный отбор выдержки (§3 Retrieve, сценарий 37).

    Порядок: явный ``offset`` (догрузка остатка) → явная ``section``
    (заголовок/номер) → семантический отбор по ``terms`` (склейка соседних
    секций, пока влезает) → начало документа. Никогда не бросает и никогда не
    режет внутри строки."""
    body = str(text or "")
    total = len(body)
    budget = max(200, int(budget_chars or 0))
    sections = split_sections(body)
    if total <= budget:
        return Excerpt(text=body, start=0, end=total,
                       line_range=(1, len(body.splitlines()) or 1),
                       total_chars=total, remainder_chars=0,
                       selected_by="whole", sections=sections,
                       truncated=False)
    # 1) догрузка остатка по offset (символы от начала документа).
    try:
        offset_value = int(offset) if offset is not None else None
    except (TypeError, ValueError):
        offset_value = None
    if offset_value is not None and offset_value > 0:
        bounded = min(offset_value, max(0, total - 1))
        line = body.count("\n", 0, bounded) + 1
        piece, start, end, end_line = _slice_by_lines(body, line, budget)
        return Excerpt(text=piece, start=start, end=end,
                       line_range=(line, end_line), total_chars=total,
                       remainder_chars=max(0, total - end),
                       selected_by="offset", sections=sections,
                       truncated=end < total)
    # 2) явная секция (заголовок или 1-based номер).
    target = None
    if section not in (None, ""):
        raw = str(section).strip().lower()
        for idx, item in enumerate(sections):
            heading = str(item.get("heading") or "").lower()
            if raw == str(idx + 1) or (heading and raw in heading):
                target = item
                break
    # 3) семантический отбор по терминам claim.
    selected_by = "start"
    if target is None and terms:
        wanted = {str(term).lower()[:6] for term in terms if str(term).strip()}
        if not wanted:
            wanted = content_terms(" ".join(str(t) for t in terms))
        best_idx, best_score = -1, 0
        for idx, item in enumerate(sections):
            first = int(item.get("start_line") or 1) - 1
            last = int(item.get("end_line") or 1)
            chunk = "\n".join(body.splitlines()[first:last]).lower()
            score = sum(1 for term in wanted if term and term in chunk)
            if score > best_score:
                best_idx, best_score = idx, score
        if best_idx >= 0 and best_score > 0:
            # склеиваем соседние секции, пока влезает в бюджет
            start_idx = end_idx = best_idx
            used = int(sections[best_idx].get("chars") or 0)
            while True:
                grew = False
                for candidate in (end_idx + 1, start_idx - 1):
                    if 0 <= candidate < len(sections):
                        add = int(sections[candidate].get("chars") or 0)
                        if used + add <= budget:
                            if candidate > end_idx:
                                end_idx = candidate
                            else:
                                start_idx = candidate
                            used += add
                            grew = True
                if not grew:
                    break
            target = {"start_line": int(sections[start_idx]["start_line"]),
                      "end_line": int(sections[end_idx]["end_line"])}
            selected_by = "terms"
    if target is None:
        piece, start, end, end_line = _slice_by_lines(body, 1, budget)
    else:
        piece, start, end, end_line = _slice_by_lines(
            body, int(target.get("start_line") or 1), budget)
    return Excerpt(text=piece, start=start, end=end,
                   line_range=(max(1, body.count("\n", 0, start) + 1), end_line),
                   total_chars=total, remainder_chars=max(0, total - end),
                   selected_by=selected_by, sections=sections,
                   truncated=end < total)


def build_source_pointer(url: str, source_id: str, *, offset: int,
                         total_chars: int, line_range=(0, 0),
                         tool: str = "fetch_article") -> dict:
    """Указатель на полный источник для догрузки существующим инструментом.

    Не часть обрезаемого текста (отдельное поле payload) — поэтому обрезка
    никогда не ломает указатель (§4.4 Preserve)."""
    pointer = {
        "tool": tool,
        "url": str(url or ""),
        "source_id": str(source_id or ""),
        "offset": int(offset or 0),
        "total_chars": int(total_chars or 0),
    }
    if line_range and int(line_range[0] or 0) > 0:
        pointer["line_range"] = [int(line_range[0]), int(line_range[1])]
    if line_range and int(line_range[0] or 0) > 0:
        pointer["call"] = (f'{tool}(url="{url}", offset={int(offset or 0)})')
    return pointer


def _extract_links(html: str, base_url: str) -> tuple[str, ...]:
    """Ссылки первоисточника отдельным безопасным списком (не в тексте).

    Только абсолютные http(s), без credentials, dedupe, bounded. Ошибка/мусор
    → пустой список (честно: `links_source="unavailable"` у вызывающего)."""
    found: list[str] = []
    seen: set[str] = set()
    base = str(base_url or "")
    for raw in _LINK_RE.findall(str(html or "")):
        candidate = str(raw or "").strip()
        if not candidate or candidate.startswith(("mailto:", "javascript:", "tel:")):
            continue
        try:
            absolute = urljoin(base, candidate)
            parts = urlsplit(absolute)
        except Exception:      # pragma: no cover - защитная ветка
            continue
        if parts.scheme not in ("http", "https"):
            continue
        if parts.username or parts.password:
            continue
        if not parts.hostname:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        found.append(absolute)
        if len(found) >= _MAX_LINKS:
            break
    return tuple(found)


def _extract_published_at(html: str) -> tuple[str, str]:
    """Дата публикации из метаданных страницы (``(value, source)``)."""
    body = str(html or "")
    for index, pattern in enumerate(_PUBLISHED_META_RES):
        match = pattern.search(body)
        if match:
            value = str(match.group(1) or "").strip()
            if value:
                return value[:64], ("meta" if index < 2 else "time")
    return "", ""


class WebContentExtractor:
    def __init__(
        self,
        tavily_api_key: str = settings.TAVILY_API_KEY,
        exa_api_key: str = settings.EXA_API_KEY,
    ) -> None:
        # Миграция read-пути: ключи из админки (keys.tavily/exa) — приоритет
        # над env (в дефолтах бейкдились бы при импорте).
        self._tavily_api_key = hot.get("keys.tavily_api_key",
                                       tavily_api_key) or ""
        self._exa_api_key = hot.get("keys.exa_api_key", exa_api_key) or ""
        self._client: httpx.AsyncClient | None = None
        # MCA-02 (ADR-1027-5 D1): общий SafeFetcher (единственный fetch-контур).
        self._safe_fetcher: safe_fetch.SafeFetcher | None = None

    def _get_safe_fetcher(self) -> safe_fetch.SafeFetcher:
        if self._safe_fetcher is None:
            self._safe_fetcher = safe_fetch.SafeFetcher()
        return self._safe_fetcher

    def _get_client(self) -> httpx.AsyncClient:
        """Ленивый общий httpx-клиент (прецедент SearchAggregator._get_client)."""
        if self._client is None:
            self._client = httpx.AsyncClient()
        return self._client

    async def extract(self, target_url: str, max_symbols: int) -> str:
        """Совместимость (D-класс preview): текст уровня-1/фолбэка, срез до
        ``max_symbols``.

        ASAP-EVIDENCE-ROUTING-01 v3: это legacy-обёртка для потребителей,
        которым нужен короткий preview (`web_summarizer_service`). Основной
        claim-bound путь инструмента — :meth:`extract_document`: reader больше
        не режет документ до 8000, ограничение делает доставка."""
        document = await self.extract_document(target_url, ceiling=None)
        return self._truncate(document.text, max_symbols)

    async def extract_document(self, target_url: str,
                              *, ceiling: int | None = None
                              ) -> ExtractedDocument:
        """Каскад trafilatura → tavily → exa. Возвращает ДОКУМЕНТ.

        Отличия от legacy ``extract`` (P0, `limits-audit.md` №4/№5/№6):
          * срез доставки убран (есть только технический ``ceiling`` из
            `auto_budget.article_extract_ceiling`), срез помечается честно;
          * короткая валидная страница (≤150 симв.) — не отказ уровня, а
            ``short_content=True`` (фолбэк всё равно пробуется);
          * ``include_links`` честен: ссылки отдаются отдельным списком
            (`links_source="html"`), а не исчезают;
          * ``published_at`` (метаданные страницы) отделён от ``retrieved_at``.

        Все уровни упали/пусто → :class:`WebContentExtractionFailedException`.
        Опасное назначение (SSRF/scheme/credentials/redirect) НЕ уходит в
        облачные фолбеки — немедленный отказ (R17: URL маскируется)."""
        levels = [
            ("trafilatura", self._extract_trafilatura, None),
            ("tavily", self._extract_tavily, self._tavily_api_key),
            ("exa", self._extract_exa, self._exa_api_key),
        ]
        last_safe_error = None
        best_short: tuple[str, str, tuple, str, str] | None = None
        tried: list[str] = []
        for name, fn, key in levels:
            if key is not None and not key.strip():
                # пустой ключ — уровень отключён (D104-прецедент)
                logger.warning(
                    "[web_extractor] level skipped (no api key) | provider=%s", name
                )
                continue
            started = time.monotonic()
            try:
                payload = await fn(target_url)
                if isinstance(payload, tuple) and len(payload) == 4:
                    text, links, published_at, published_source = payload
                else:
                    # Совместимость с подменёнными/устаревшими уровнями,
                    # возвращающими только текст (прежний контракт).
                    text, links, published_at, published_source = (
                        payload, (), "", "")
                tried.append(f"{name}:ok")
                latency_ms = (time.monotonic() - started) * 1000.0
                stripped = str(text or "").strip()
                short = len(stripped) <= _MIN_CONTENT_CHARS
                if short:
                    # Порог — решение «пробовать ли следующий уровень», НЕ
                    # отказ: короткий официальный текст может быть полным.
                    logger.info(
                        "[web_extractor] level short_content | provider=%s | "
                        "chars=%d | (fallback продолжается)", name, len(stripped))
                    if stripped and (best_short is None
                                     or len(stripped) > len(best_short[0])):
                        best_short = (stripped, name, tuple(links or ()),
                                      str(published_at or ""),
                                      str(published_source or ""))
                    continue
                logger.info(
                    "[web_extractor] level ok | provider=%s | latency_ms=%.0f | chars=%d",
                    name, latency_ms, len(text),
                )
                return self._finalize_document(
                    target_url, str(text), name, links,
                    published_at, published_source, ceiling, tuple(tried),
                    short_content=False)
            except safe_fetch.SafeFetchError as exc:
                last_safe_error = exc
                if exc.code in _POLICY_BLOCK_CODES:
                    logger.warning(
                        "[web_extractor] destination blocked — no fallback "
                        "| code=%s | url=%s", exc.code,
                        safe_fetch.mask_url(target_url))
                    raise WebContentExtractionFailedException(
                        f"destination blocked | code={exc.code}",
                        safe_error=exc) from exc
                tried.append(f"{name}:{exc.code}")
                logger.warning(
                    "[web_extractor] level failed → fallback | provider=%s | error=%s",
                    name, exc,
                )
            except Exception as exc:
                tried.append(f"{name}:{type(exc).__name__}")
                logger.warning(
                    "[web_extractor] level failed → fallback | provider=%s | error=%s",
                    name, exc,
                )
        if best_short is not None:
            # Ни один уровень не дал длинный текст, но короткая валидная
            # страница есть → отдаём её (не ложный «источник недоступен»).
            stripped, name, links, published_at, published_source = best_short
            return self._finalize_document(
                target_url, stripped, name, links,
                published_at, published_source, ceiling,
                tuple(tried), short_content=True)
        logger.error("[web_extractor] all levels failed | url=%s",
                     safe_fetch.mask_url(target_url))
        raise WebContentExtractionFailedException(
            f"all extraction levels failed | url={safe_fetch.mask_url(target_url)}",
            safe_error=last_safe_error
        )

    @staticmethod
    def _finalize_document(target_url: str, text: str, provider: str, links,
                           published_at: str, published_source: str,
                           ceiling: int | None, tried: tuple[str, ...],
                           *, short_content: bool) -> ExtractedDocument:
        """Собрать `ExtractedDocument` с честным техническим ceiling'ом.

        ``total_chars`` — РЕАЛЬНЫЙ объём извлечённого текста ДО обрезки
        ceiling'ом: иначе вызывающий видел бы «total == доставлено» и не мог
        отличить «документ кончился» от «обрезано при извлечении». Сам текст
        и ``truncated_at_extraction`` по-прежнему отражают доставленное."""
        body = str(text or "")
        real_total = len(body)
        cap = int(ceiling or 0)
        truncated = bool(cap and real_total > cap)
        if truncated:
            logger.warning(
                "[web_extractor] extraction ceiling reached | provider=%s | "
                "total=%d | ceiling=%d", provider, real_total, cap)
            body = body[:cap]
        return ExtractedDocument(
            url=str(target_url or ""), text=body, provider=provider,
            short_content=bool(short_content),
            links=tuple(links or ()),
            links_source="html" if links else "unavailable",
            published_at=str(published_at or ""),
            published_at_source=str(published_source or ""),
            total_chars=real_total, ceiling=cap,
            truncated_at_extraction=truncated, levels_tried=tried)

    async def _extract_trafilatura(self, target_url: str
                                   ) -> tuple[str, tuple[str, ...], str, str]:
        """Шаг 1 (основной): GET target_url (UA, redirects) → trafilatura.

        MCA-02 (ADR-1027-5 D1/D3/D5): при `MCA_SAFE_FETCH_ENABLED` загрузка
        идёт через общий SafeFetcher (нормализация/SSRF/redirect/peer-проверка/
        потоковые лимиты). OFF → точный legacy-путь (паритет baseline).

        SOUL-13/SSRF-guard: состояние гарда читается ПЕРВЫМ — его позиция не
        зависит от наличия опционального пакета trafilatura. Если пакета нет
        (уровень-1 недоступен), pre-flight назначения всё равно выполняется до
        выхода в облачные фолбеки: иначе SSRF-инвариант «опасное назначение не
        уходит в Tavily/Exa» держался бы только при установленной trafilatura.

        ASAP-EVIDENCE-ROUTING-01 v3: возвращает ``(text, links, published_at,
        published_at_source)``; ссылки/дата берутся из ТОГО ЖЕ HTML (без
        второго запроса), ``include_links`` больше не теряет первоисточники."""
        safe_fetch_on = mca_gates.safe_fetch_enabled()
        if trafilatura is None:
            # Уровень-1 недоступен: страница не качается, нужен только
            # pre-flight политики (normalize/credentials/SSRF-адреса), чтобы
            # опасный URL не ушёл в облачные фолбеки.
            if safe_fetch_on:
                await safe_fetch.aguarded_target(target_url, trusted=False)
            raise RuntimeError("trafilatura is not installed")
        client = self._get_client()
        if safe_fetch_on:
            response = await self._get_safe_fetcher().fetch(
                target_url, profile="html", client=client,
                headers={"User-Agent": _USER_AGENT})
            if response.status_code >= 400:
                raise httpx.HTTPStatusError(
                    f"safe_fetch HTTP {response.status_code}",
                    request=httpx.Request("GET", target_url),
                    response=httpx.Response(response.status_code))
            html = response.text()
        else:
            legacy = await client.get(
                target_url,
                headers={"User-Agent": _USER_AGENT},
                follow_redirects=True,
                timeout=httpx.Timeout(_FETCH_TIMEOUT),
            )
            legacy.raise_for_status()
            html = legacy.text
        text = await asyncio.to_thread(
            trafilatura.extract,
            html,
            output_format="markdown",
            include_links=False,
            include_images=False,
            include_tables=True,
            favor_precision=True,
        )
        if text is None:
            raise ValueError("trafilatura: no extractable content")
        links = _extract_links(html, target_url)
        published_at, published_source = _extract_published_at(html)
        return str(text), links, published_at, published_source

    async def _extract_tavily(self, target_url: str
                              ) -> tuple[str, tuple[str, ...], str, str]:
        """Шаг 2 (фолбек №1): POST api.tavily.com/extract,
        json={"urls":[target_url],"api_key":…}, timeout 15.0 (ТЗ).
        Возвращает results[0]["raw_content"]; пусто → raise.

        Ссылки/дата недоступны на облачном уровне → пустой список и
        ``links_source="unavailable"`` (честно, без выдумок)."""
        client = self._get_client()
        response = await client.post(
            TAVILY_EXTRACT_URL,
            json={"urls": [target_url], "api_key": self._tavily_api_key},
            timeout=httpx.Timeout(_API_TIMEOUT),
        )
        response.raise_for_status()
        results = response.json().get("results") or []
        if not results or not str(results[0].get("raw_content") or "").strip():
            raise ValueError("tavily: empty raw_content")
        return str(results[0]["raw_content"]), (), "", ""

    async def _extract_exa(self, target_url: str
                           ) -> tuple[str, tuple[str, ...], str, str]:
        """Шаг 3 (фолбек №2): POST api.exa.ai/contents,
        headers={"x-api-key":…}, json={"urls":[target_url],"text":True},
        timeout 15.0 (ТЗ). Возвращает results[0]["text"]; пусто → raise."""
        client = self._get_client()
        response = await client.post(
            EXA_CONTENTS_URL,
            headers={"x-api-key": self._exa_api_key},
            json={"urls": [target_url], "text": True},
            timeout=httpx.Timeout(_API_TIMEOUT),
        )
        response.raise_for_status()
        results = response.json().get("results") or []
        if not results or not str(results[0].get("text") or "").strip():
            raise ValueError("exa: empty text")
        return str(results[0]["text"]), (), "", ""

    async def close(self) -> None:
        """Закрыть ленивые клиенты (on_shutdown, прецедент Epic 33/37)."""
        if self._safe_fetcher is not None:
            await self._safe_fetcher.aclose()
            self._safe_fetcher = None
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def log_config(self) -> None:
        """WARNING пустых ключей при старте (bot.py on_startup, прецедент D104)."""
        if not (self._tavily_api_key or "").strip():
            logger.warning("Tavily extract level disabled: TAVILY_API_KEY is empty")
        if not (self._exa_api_key or "").strip():
            logger.warning("Exa contents level disabled: EXA_API_KEY is empty")

    @staticmethod
    def _truncate(text: str, max_symbols: int) -> str:
        """Жёсткий срез (прецедент SearchAggregator._truncate)."""
        return text[:max_symbols]
