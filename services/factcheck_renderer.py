"""CFG-06 W5 — детерминированный Telegram-renderer фактчека (06E, бриф §W5).

``FactcheckPresentation`` (+ ``CheckedVerdict`` для enum-вердикта) →
безопасный Telegram-HTML: bold-вердикт по enum CheckedVerdict (человеческая
фраза, без маркеров/emoji), 2–4 пункта сути (детерминированный сплит по
предложениям, порядок сохранён), ссылки ТОЛЬКО из EvidenceMap текущего
прогона (``presentation.links``; scheme-whitelist http/https), честная
формулировка ограничения при отсутствии ссылок (CFG-06.B).

Контракты:

* LLM HTML не генерирует — всю разметку строит этот модуль; любой
  пользовательский текст экранируется (html.escape), инъекция тегов из
  вердикта/URL невозможна;
* ``render_factcheck`` не меняет факты/числа/ссылки вербализатора —
  только структуру и экранирование (все предложения сохраняются);
* FC-RENDER (owner 21.10.2026 §3.6): ссылки привязываются к утверждениям
  (части вердикта с evidence_refs), у каждого источника объясняется роль
  (первоисточник/исследование/энциклопедия/пересказ/чат), непроцитированные
  хосты не выводятся списком «на всякий случай»; url=None строки в
  источниках не участвуют; рендеринг не искажает вердикт аналитика;
* доставка — через СУЩЕСТВУЮЩИЙ ``send_chunked_reply(parse_mode=...)``
  (общая функция в smartmodule_utils НЕ меняется): pre-split на
  entity-safe чанки (теги не рвутся, каждая часть ≤ лимита), reply только
  у первой части, TelegramBadRequest парсинга → деградация ЧАНКА в plain;
* OFF-паритет: renderer вызывается только внутри v2-оркестратора
  (``FACTCHECK_PIPELINE_V2_ENABLED``); прод-путь 2.58.98 его не импортирует.

Схемы — фриз W3 (w3-schemas.md §1): поля FactcheckPresentation/
CheckedVerdict не меняются; renderer — потребитель.
"""
from __future__ import annotations

import dataclasses
import html
import logging
import re
from urllib.parse import urlsplit

from aiogram.exceptions import TelegramBadRequest

from services.factcheck_orchestrator import (
    CheckedVerdict,
    FactcheckPresentation,
)
from services.smartmodule_utils import _CHUNK_LIMIT, send_chunked_reply

logger = logging.getLogger(__name__)

FACTCHECK_PARSE_MODE = "HTML"

#: Человеческие фразы вердикта по enum FACTUAL_VERDICTS (temporal_factcheck).
#: Без маркеров/emoji/тех-скобок; неизвестный enum → заголовка НЕТ
#: (renderer не выдумывает вердикт, которого нет в CheckedVerdict).
_VERDICT_HEADLINE = {
    "supported": "Подтверждается",
    "refuted": "Не подтверждается",
    "mixed": "Подтверждается частично",
    "insufficient_evidence": "Недостаточно данных для проверки",
}

#: Честное ограничение при evidence без URL (CFG-06.B: «подтверждает
#: реальными источниками или честно сообщает ограничение»).
_NO_LINKS_NOTICE = (
    "Первоисточники в этот раз открыть не удалось — вывод сделан по "
    "выдержкам без проверяемых ссылок.")

#: FC-RENDER (owner §3.6): роль каждого источника объясняется — списка
#: доменов без объяснения больше нет. source_kind → человеческая роль
#: (доступность источника, не истинность утверждений).
_SOURCE_KIND_LABELS = {
    "primary": "первоисточник",
    "research": "исследование",
    "reference": "энциклопедия",
    "secondary": "пересказ",
    "chat": "сообщение чата",
}

#: FC-PERCLAIM/FC-RENDER: короткие подписи вердикта части при разборе.
_PART_LABELS = {
    "supported": "подтверждается",
    "refuted": "не подтверждается",
    "mixed": "подтверждается частично",
    "insufficient_evidence": "данных недостаточно",
}

_MAX_BOUND_PARTS = 4              # bound: разбор ≤4 ключевых утверждений
_PART_TEXT_MAX_CHARS = 110

_MAX_POINTS = 4                      # 2–4 пункта сути (бриф W5)

_SENT_SPLIT_RE = re.compile(r"(?<=[.!?…])\s+")
_TAG_RE = re.compile(r"<[^>]+>")
_URL_SAFE_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)


# ── Безопасные атомы ─────────────────────────────────────────────────────────

def visible_text(markup: str) -> str:
    """Видимый текст без тегов (контракт-тесты: URL не в видимом тексте)."""
    return html.unescape(_TAG_RE.sub("", str(markup or ""))).strip()


def _esc(text: str) -> str:
    return html.escape(str(text or ""), quote=False)


def _esc_attr(text: str) -> str:
    return html.escape(str(text or ""), quote=True)


def _safe_host(url: str) -> str:
    try:
        host = urlsplit(str(url or "")).netloc.lower()
    except ValueError:
        return ""
    return host[4:] if host.startswith("www.") else host


def _safe_links(links) -> tuple[str, ...]:
    """Whitelist: только http/https без пробелов, без дублей, порядок."""
    out: list[str] = []
    for url in links or ():
        u = str(url or "").strip()
        if _URL_SAFE_RE.match(u) and u not in out:
            out.append(u)
    return tuple(out)


# ── Детерминированная структура ──────────────────────────────────────────────

def _sentences(text: str) -> list[str]:
    return [s.strip() for s in _SENT_SPLIT_RE.split(str(text or ""))
            if s.strip()]


def _points(text: str) -> list[str] | None:
    """2–4 пункта сути: предложения → ≤4 ПОДРЯД идущих групп (порядок и
    состав сохранены — ни одно предложение не выбрасывается и не меняется).
    Одиночное предложение → None (один абзац, список не нужен)."""
    sents = _sentences(text)
    if len(sents) <= 1:
        return None
    n = min(_MAX_POINTS, len(sents))
    base, extra = divmod(len(sents), n)
    groups: list[str] = []
    i = 0
    for g in range(n):
        size = base + (1 if g < extra else 0)
        groups.append(" ".join(sents[i:i + size]))
        i += size
    return groups


def _content(presentation: FactcheckPresentation,
             verdict: CheckedVerdict | None):
    """Единая контент-модель для HTML- и plain-сериализации."""
    headline = (_VERDICT_HEADLINE.get(verdict.factual_verdict)
                if verdict is not None else None)
    links = _safe_links(presentation.links)
    if verdict is not None:
        # FC-RENDER (§3.6): есть цитаты аналитика → показываем ТОЛЬКО
        # процитированные URL (непроцитированные хосты не «мусорный
        # список»); без цитат — прежний список всех ссылок прогона.
        cited = {str(r) for r in (verdict.evidence_refs or ())}
        if cited:
            refs = _refs_by_id(verdict)
            cited_urls = {refs[r].url for r in cited if r in refs}
            if cited_urls:
                links = tuple(u for u in links if u in cited_urls)
    notice = str(presentation.notice or "").strip()
    if not links and not notice and verdict is not None \
            and verdict.evidence.refs:
        notice = _NO_LINKS_NOTICE
    return headline, str(presentation.text or ""), links, notice


def _trim(text: str, limit: int = _PART_TEXT_MAX_CHARS) -> str:
    cleaned = " ".join(str(text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit - 1].rstrip() + "…"


def _refs_by_id(verdict: CheckedVerdict | None) -> dict:
    if verdict is None or verdict.evidence is None:
        return {}
    return {ref.evidence_id: ref for ref in verdict.evidence.refs if ref.url}


def _part_bindings(verdict: CheckedVerdict | None) -> list:
    """FC-RENDER (§3.6): (текст части, вердикт части, [EvidenceRef]) —
    разбор ключевых утверждений с цитатами, привязанными к каждому.
    Только URL из EvidenceMap текущего прогона (allowlist уже проверен
    сервером в verdict_from_payload)."""
    if verdict is None:
        return []
    refs = _refs_by_id(verdict)
    out = []
    seen_texts: set[str] = set()
    for part in (verdict.parts or ()):
        if not isinstance(part, dict) or len(out) >= _MAX_BOUND_PARTS:
            break
        text = str(part.get("text") or "").strip()
        if not text:
            continue
        key = text.lower()[:100]
        if key in seen_texts:
            continue
        part_refs = [refs[str(r)] for r in (part.get("evidence_refs") or ())
                     if isinstance(r, str) and str(r) in refs]
        if not part_refs:
            continue
        seen_texts.add(key)
        out.append((text, str(part.get("factual_verdict") or ""), part_refs))
    return out


def _sources_rows(verdict: CheckedVerdict | None, links, *,
                  bound_urls: set, esc, esc_attr, html_mode: bool
                  ) -> list[str]:
    """Строки «Источники:» с ролью каждого источника (FC-RENDER §3.6:
    никаких доменов без объяснения); ссылки, уже привязанные к частям,
    во втором списке не повторяются."""
    kind_by_url: dict = {}
    if verdict is not None and verdict.evidence is not None:
        for ref in verdict.evidence.refs:
            if ref.url and ref.url not in kind_by_url:
                kind_by_url[ref.url] = _SOURCE_KIND_LABELS.get(
                    ref.source_kind, "")
    rows: list[str] = []
    for url in links:
        if url in bound_urls:
            continue
        kind = kind_by_url.get(url, "")
        label = _safe_host(url) or "источник"
        suffix = f" — {kind}" if kind else ""
        if html_mode:
            rows.append(f"{len(rows) + 1}. <a href=\"{esc_attr(url)}\">"
                        f"{esc(label)}</a>{esc(suffix)}")
        else:
            rows.append(f"{len(rows) + 1}. {url}{suffix}")
    return rows


def _serialize(presentation: FactcheckPresentation,
               verdict: CheckedVerdict | None, *, html_mode: bool) -> str:
    headline, body, links, notice = _content(presentation, verdict)
    esc = _esc if html_mode else (lambda s: s)
    esc_attr = _esc_attr if html_mode else (lambda s: s)
    blocks: list[str] = []
    if headline:
        headline = str(headline)
        blocks.append(f"<b>{esc(headline)}</b>" if html_mode else headline)
    points = _points(body)
    if points:
        blocks.append("\n".join("• " + esc(p) for p in points))
    elif body.strip():
        blocks.append(esc(body.strip()))
    # FC-RENDER: разбор ключевых утверждений с цитатами при каждом тезисе +
    # роль каждого источника. Без вердикта (legacy plain) — прежний список.
    bindings = _part_bindings(verdict)
    if bindings:
        lines: list[str] = []
        for text, part_verdict, part_refs in bindings:
            label = _PART_LABELS.get(part_verdict)
            cites = []
            for ref in part_refs:
                host = _safe_host(ref.url) or "источник"
                if html_mode:
                    cites.append(f"<a href=\"{esc_attr(ref.url)}\">"
                                 f"{esc(host)}</a>")
                else:
                    cites.append(ref.url)
            cites_text = ", ".join(cites)
            trimmed = _trim(text)
            if html_mode:
                prefix = f"• {esc(trimmed)} — {esc(label)}: " if label \
                    else f"• {esc(trimmed)}: "
                lines.append(prefix + cites_text)
            else:
                prefix = f"• {trimmed} — {label}: " if label \
                    else f"• {trimmed}: "
                lines.append(prefix + cites_text)
        blocks.append("По утверждениям:\n" + "\n".join(lines))
    bound_urls = {ref.url for _t, _v, refs in bindings for ref in refs}
    rows = _sources_rows(verdict, links, bound_urls=bound_urls,
                         esc=esc, esc_attr=esc_attr, html_mode=html_mode)
    if rows:
        blocks.append("Источники:\n" + "\n".join(rows))
    if notice:
        blocks.append(f"<i>{esc(notice)}</i>" if html_mode else notice)
    return "\n\n".join(blocks) if blocks else esc(body.strip())


# ── Публичный API ────────────────────────────────────────────────────────────

def render_factcheck(presentation: FactcheckPresentation,
                     verdict: CheckedVerdict | None = None,
                     ) -> FactcheckPresentation:
    """Детерминированный рендер → НОВАЯ FactcheckPresentation (frozen) с
    ``parse_mode="HTML"``. Структура добавляется, факты не меняются.
    Любой сбой → та же презентация без parse_mode (plain-паритет)."""
    try:
        text = _serialize(presentation, verdict, html_mode=True)
        return dataclasses.replace(presentation, text=text,
                                   parse_mode=FACTCHECK_PARSE_MODE)
    except Exception:
        logger.warning("[factcheck_v2] renderer failed — plain passthrough",
                       exc_info=True)
        return dataclasses.replace(presentation, parse_mode=None)


def render_plain(presentation: FactcheckPresentation,
                 verdict: CheckedVerdict | None = None,
                 ) -> FactcheckPresentation:
    """Plain-деградация (06E.6): та же контент-модель без разметки."""
    return dataclasses.replace(
        presentation,
        text=_serialize(presentation, verdict, html_mode=False),
        parse_mode=None)


# ── Entity-safe нарезка ──────────────────────────────────────────────────────

def _split_long_line(line: str, limit: int) -> list[str]:
    """Строка длиннее лимита → куски по пробелам (разметка renderer'а не
    делает тегированные строки длиннее лимита; длинная строка — это
    безтеговый абзац, резать безопасно)."""
    out: list[str] = []
    cur = ""
    for word in line.split(" "):
        cand = f"{cur} {word}" if cur else word
        if len(cand) > limit and cur:
            out.append(cur)
            cur = word
        else:
            cur = cand
    if cur:
        out.append(cur)
    return out


def split_entity_safe(text: str, limit: int = _CHUNK_LIMIT) -> list[str]:
    """Нарезка готовой разметки на части ≤ limit по СТРОКАМ: теги renderer'а
    никогда не пересекают границу строки, поэтому каждая часть — валидный
    HTML сама по себе (entities/Unicode не рвутся). Пустые строки на
    границах частей срезаются."""
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    current: list[str] = []
    size = 0

    def _flush() -> None:
        nonlocal current, size
        while current and not current[0]:
            current.pop(0)
        while current and not current[-1]:
            current.pop()
        if current:
            chunks.append("\n".join(current))
        current, size = [], 0

    for line in str(text).split("\n"):
        pieces = [line] if len(line) <= limit else _split_long_line(line,
                                                                    limit)
        for piece in pieces:
            add = len(piece) + (1 if current else 0)
            if size + add > limit and current:
                _flush()
                add = len(piece)
            current.append(piece)
            size += add
    _flush()
    return chunks or [text[:limit]]


# ── Доставка (через СУЩЕСТВУЮЩИЙ send_chunked_reply) ────────────────────────

async def deliver_factcheck(bot, chat_id: int,
                            presentation: FactcheckPresentation, *,
                            reply_to_message_id: int | None = None) -> None:
    """Доставка презентации: СУЩЕСТВУЮЩИЙ ``send_chunked_reply`` (общая
    функция НЕ меняется). С HTML — pre-split entity-safe чанков, reply
    только у первой части; TelegramBadRequest парсинга → деградирует
    ТОЛЬКО сломанный чанк (в plain), остальные идут как есть."""
    if not presentation.parse_mode:
        await send_chunked_reply(bot, chat_id, presentation.text,
                                 reply_to_message_id)
        return
    rid = reply_to_message_id
    for chunk in split_entity_safe(presentation.text, _CHUNK_LIMIT):
        try:
            await send_chunked_reply(bot, chat_id, chunk, rid,
                                     parse_mode=presentation.parse_mode)
        except TelegramBadRequest:
            logger.warning("[factcheck_v2] HTML chunk failed — plain "
                           "degradation | chat=%s", chat_id, exc_info=True)
            await send_chunked_reply(bot, chat_id, visible_text(chunk), rid)
        rid = None
