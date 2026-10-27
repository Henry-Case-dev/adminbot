"""CFG-06 W5 — детерминированный Telegram-renderer фактчека (06E, бриф §W5).

``FactcheckPresentation`` (+ ``CheckedVerdict`` для enum-вердикта) →
безопасный Telegram-HTML: bold-вердикт по enum CheckedVerdict (человеческая
фраза, без маркеров/emoji), тело вербализатора проходит как есть
(P0-FACTCHECK-CORRECTIVE §7.4: обязательная композиция/принудительный
список сняты — структура определяется фактическим содержанием), ссылки
ТОЛЬКО из EvidenceMap текущего прогона (``presentation.links``;
scheme-whitelist http/https), честная формулировка ограничения при
отсутствии ссылок (CFG-06.B). Техническое ограничение выводится один раз
(P0-FACTCHECK-CORRECTIVE §7.3: заголовок исключает дублирующую концовку).

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

#: P0-FACTCHECK (§3.6, owner 24.10.2026): технический исход НЕ прячется за
#: универсальным «Недостаточно данных» — отдельный заголовок по reason-коду
#: прогона (существующие коды реестра; новых не выдумываем).
_TECHNICAL_HEADLINE = {
    "deadline_exceeded": "Проверка не завершена: истёк лимит времени",
    "provider_unavailable": "Проверка не завершена: поиск недоступен",
    "source_missing": "Проверка не завершена: материалы не удалось разобрать",
}

#: Пояснение к техническому исходу (когда вербализатор не сказал этого сам).
_TECHNICAL_NOTICE = {
    "deadline_exceeded": ("Поиск был прерван по лимиту времени — это "
                          "ограничение проверки, а не опровержение."),
    "provider_unavailable": ("Поисковые сервисы не ответили — это "
                             "технический сбой, а не отсутствие фактов."),
    "source_missing": ("Первоисточники открыть не удалось — вывод сделан "
                       "по выдержкам без проверяемых ссылок."),
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


def _content(presentation: FactcheckPresentation,
             verdict: CheckedVerdict | None):
    """Единая контент-модель для HTML- и plain-сериализации.

    P0-FACTCHECK-CORRECTIVE (§7.3): техническое ограничение выводится
    ОДИН раз — заголовок по reason-коду исключает второй перенос того же
    ограничения отдельной концовкой. P0-FACTCHECK-CORRECTIVE (§7.4):
    обязательная композиция тела (принудительный список 2–4 пунктов)
    снята — тело вербализатора проходит как есть."""
    technical = (_TECHNICAL_HEADLINE.get(str(verdict.reason_code or ""))
                 if verdict is not None else None)
    headline = technical or (_VERDICT_HEADLINE.get(verdict.factual_verdict)
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
    # §7.3: технический сбой объясняется явно, но ОДИН раз: при техническом
    # заголовке отдельная концовка с тем же ограничением не добавляется
    # (заголовок + абзац + концовка = три одинаковых сообщения — снято).
    technical_notice = _TECHNICAL_NOTICE.get(str(
        verdict.reason_code or "")) if verdict is not None else None
    if technical_notice and technical_notice not in notice and not technical:
        notice = f"{notice} {technical_notice}".strip() if notice \
            else technical_notice
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
    сервером в verdict_from_payload).

    P0-FACTCHECK (§3.5): часть без привязки к источнику НЕ выпадает из
    разбора — иначе «неподтверждённая часть» исчезала и общий вердикт
    выглядел полным. Такая часть показывается без ссылок."""
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
    # P0-FACTCHECK-CORRECTIVE (§7.4): обязательная композиция снята — тело
    # вербализатора (его собственная структура и длина) проходит как есть;
    # принудительный список «2–4 пункта» больше не создаётся. Разбор
    # ключевых утверждений и привязка реальных источников сохранены.
    if body.strip():
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
            label_part = f" — {esc(label)}" if (label and html_mode) else \
                (f" — {label}" if label else "")
            body_text = esc(trimmed) if html_mode else trimmed
            if cites_text:
                line = f"{body_text}{label_part}: {cites_text}"
            else:
                # P0-FACTCHECK: часть без источника остаётся видимой и
                # честно помечена (не «факт без ссылки» и не выброшена).
                line = f"{body_text}{label_part} (проверяемой ссылки нет)"
            lines.append("• " + line)
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
