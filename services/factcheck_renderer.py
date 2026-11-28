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
    EXECUTION_PARTIAL,
    EXECUTION_TECHNICAL_UNVERIFIED,
    CheckedVerdict,
    FactcheckPresentation,
)
from services.factcheck_prompts import (
    CRITIQUE_POLICY_FORBIDDEN,
    critique_policy_for_verdict,
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

#: FCT-023 (S4 U3): форма публикации — отдельная ось от source_kind.
#: Русские подписи владельца (§3.7 контракта S4): научная статья, препринт,
#: пресс-релиз, пересказ, авторская интерпретация. Неизвестное — без подписи
#: (renderer не выдумывает тип публикации).
_PUBLICATION_KIND_LABELS = {
    "preprint": "препринт",
    "journal_article": "научная статья",
    "press_release": "пресс-релиз",
    "secondary_report": "пересказ",
    "interpretation": "авторская интерпретация",
}

#: FCT-023 (S4 U3, D2): пресс-релиз и авторская интерпретация не выглядят
#: «доказательством напрямую» — рядом с подписью честная пометка. Роль/сила
#: уже понижены evidence-слоем (U1); здесь только публичная формулировка.
_NON_DIRECT_PUBLICATION_KINDS = frozenset({"press_release", "interpretation"})
_NON_DIRECT_PUBLICATION_NOTE = "не прямое доказательство"

#: FC-PERCLAIM/FC-RENDER: короткие подписи вердикта части при разборе.
_PART_LABELS = {
    "supported": "подтверждается",
    "refuted": "не подтверждается",
    "mixed": "подтверждается частично",
    "insufficient_evidence": "данных недостаточно",
}

#: Reviewer F3: технический исход части НЕ называется «данных недостаточно» —
#: иначе сбой поиска читается как отсутствие фактов (§ 4 задания).
_TECHNICAL_PART_LABELS = {
    "provider_error": "поиск не завершён: технический сбой",
    "provider_timeout": "поиск не завершён: таймаут",
    "rate_limit": "поиск не завершён: лимит запросов",
    "deadline_exceeded": "поиск не завершён: лимит времени",
    "resource_limit": "поиск не завершён: лимит ресурсов",
    "source_unreadable": "источник недоступен",
    "source_extract_failed": "источник не удалось открыть",
    "search_not_started": "пункт не проверялся",
    "claim_unidentified": "пункт не опознан",
    "cancelled": "проверка отменена",
}

#: Технический заголовок по преобладающему техническому исходу частей.
_TECHNICAL_STATUS_HEADLINE = {
    "provider_error": "Проверка не завершена: поиск недоступен",
    "deadline_exceeded": "Проверка не завершена: истёк лимит времени",
    "source_extract_failed":
        "Проверка не завершена: материалы не удалось разобрать",
}

#: FCT-602/603/193 (S4 U3): `execution_status=technical_unverified` — отдельная
#: ось вердикта, её реальная причина (`execution_cause`) называется по-русски.
#: Никаких внутренних ID/кодов/имён провайдеров: только человеческая причина.
_EXECUTION_TECHNICAL_HEADLINE = {
    "provider_error": "Проверка не завершена: поиск недоступен",
    "provider_timeout": "Проверка не завершена: поиск не ответил вовремя",
    "rate_limit": "Проверка не завершена: превышен лимит запросов",
    "deadline_exceeded": "Проверка не завершена: истёк лимит времени",
    "resource_limit": "Проверка не завершена: исчерпан лимит проверки",
    "source_unreadable": "Проверка не завершена: источники не удалось прочитать",
    "source_extract_failed":
        "Проверка не завершена: материалы не удалось разобрать",
    "cancelled": "Проверка не завершена: проверка отменена",
    "claim_unidentified": "Проверка не завершена: тезис не удалось выделить",
}
_EXECUTION_TECHNICAL_FALLBACK = "Проверка не завершена: техническая ошибка"

#: FCT-602 (S4 U3): `execution_status=partial` — подтверждённые части остаются,
#: но рядом короткая человеческая оговорка о неполноте (причина — без ID).
_PARTIAL_CAUSE_NOTICE = {
    "provider_error": "поисковые сервисы не ответили",
    "provider_timeout": "поиск не ответил вовремя",
    "rate_limit": "поисковый сервис ограничил частоту запросов",
    "deadline_exceeded": "истёк лимит времени проверки",
    "resource_limit": "исчерпан лимит проверки",
    "source_unreadable": "часть источников не удалось прочитать",
    "source_extract_failed": "часть материалов не удалось разобрать",
    "cancelled": "проверка была остановлена",
    "claim_unidentified": "часть тезисов не удалось выделить",
}
_PARTIAL_NOTICE = "Проверено частично: часть пунктов осталась без проверки"
_PARTIAL_NOTICE_SUFFIX = " — это не опровержение."

#: FCT-702 (S4 U3): оговорка непроверенного изображения — только у затронутой
#: части (caption/OCR), а не у всей публикации.
_MEDIA_PART_NOTE = ("изображение не проверено — оговорка относится только "
                    "к этому пункту")

#: §3.1/§4 (ASAP-FC-EVIDENCE-STYLE-02): показываются ВСЕ проверенные части
#: составной новости. ASAP-FC-VOICE-01 / A (§5 контракта): предел числа
#: частей снят — список частей стал fallback-публикацией проверенных данных
#: (тело Writer'а пустое), и молчаливая потеря тезисов там недопустима.
_PART_TEXT_MAX_CHARS = 120

_TAG_RE = re.compile(r"<[^>]+>")
_URL_SAFE_RE = re.compile(r"^https?://\S+$", re.IGNORECASE)

#: EVOL §5 (W5): Writer начинает отдельный раздел этой строкой. Заголовок
#: ищется в любом месте текста (после перевода строки/конца предложения или
#: в начале) — egress-guard может схлопнуть переводы строк, и тогда раздел
#: всё равно должен остаться отдельным блоком, а не раствориться в абзаце.
_CRITIQUE_HEADING_RE = re.compile(
    r"(?P<prefix>^|[\n]|[.!?…]\s+)[ \t*_#>\"«]*"
    r"критическ\w*[ \t]+разнос\w*[ \t]*[:\-—–]?[ \t]*",
    re.IGNORECASE | re.MULTILINE)


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


def split_critique_section(text: str) -> tuple[str, str]:
    """Разделить публичный текст Writer'а на ``(основной разбор, разнос)``.

    EVOL §5 (W5): раздел «Критический разнос» генерируется в ТОЙ ЖЕ
    Writer-фазе, но публикуется отдельным блоком renderer'а (не сливается с
    источниками, переживает HTML/чанкинг). Заголовок распознаётся как
    отдельная строка (или после конца предложения — egress-guard может
    схлопнуть переводы строк). Заголовка нет/раздел пуст → ``(text, "")``:
    renderer не выдумывает раздел, которого Writer не написал.
    """
    body = str(text or "")
    match = _CRITIQUE_HEADING_RE.search(body)
    if match is None:
        return body, ""
    prefix = match.group("prefix") or ""
    head = body[:match.start()] + prefix
    tail = body[match.end():].strip()
    if not tail:
        return body, ""
    head = head.strip()
    if not head:
        # Раздел оказался единственным содержанием: оставляем как тело,
        # чтобы не отправить пустое сообщение с одним заголовком.
        return body, ""
    return head, tail


def critique_publishable(verdict: CheckedVerdict | None, *,
                         allow_critique: bool = True) -> bool:
    """Детерминированный gate жанровой директивы критики (промпт, не текст).

    SEMANTIC GUARD §5.1/§5.2 (сервер, не пожелание модели): директива
    критики попадает в промпт только когда прогон УЖЕ установил ошибку/
    подмену, есть доказательства и настройка «Критический разнос» включена.

    ASAP-FC-VOICE-01 / A (§5 контракта): этот предикат больше не управляет
    ФОРМОЙ публикации (renderer не создает и не режет раздел) — он остался
    серверной проверкой «есть ли установленная ошибка», пригодной для
    диагностики и для будущих швов. Рабочий гейт промпта — политика
    ``factcheck_prompts.critique_policy_for_*``.
    """
    if not allow_critique or verdict is None:
        return False
    policy = critique_policy_for_verdict(
        factual_verdict=verdict.factual_verdict,
        parts=tuple(verdict.parts or ()),
        reason_code=verdict.reason_code,
        fallback_used=bool(verdict.fallback_used),
        has_evidence=bool(verdict.evidence is not None
                          and verdict.evidence.refs))
    return policy != CRITIQUE_POLICY_FORBIDDEN


def headline_code(verdict: CheckedVerdict | None) -> str:
    """§11.3: КОД финального заголовка (не текст) — для трассы прогона.

    Порядок тот же, что в ``_content``: техническая причина прогона →
    технические статусы частей → вердикт. Расхождение с ``_content``
    невозможно по построению (одни и те же предикаты)."""
    if verdict is None:
        return ""
    execution_status = str(getattr(verdict, "execution_status", "") or "")
    execution_cause = str(getattr(verdict, "execution_cause", "") or "")
    if execution_status == EXECUTION_TECHNICAL_UNVERIFIED:
        reason = str(verdict.reason_code or "")
        if reason in _TECHNICAL_HEADLINE:
            return f"technical:{reason}"
        return f"technical:execution:{execution_cause or 'unknown'}"
    if execution_status == EXECUTION_PARTIAL:
        # partial: содержательный заголовок + оговорка (см. `_content`).
        factual = str(verdict.factual_verdict or "")
        return f"verdict:{factual}" if factual in _VERDICT_HEADLINE else ""
    reason = str(verdict.reason_code or "")
    if reason in _TECHNICAL_HEADLINE:
        return f"technical:{reason}"
    from_parts = _technical_headline_from_parts(verdict)
    if from_parts:
        statuses = _technical_statuses(verdict)
        return f"parts:{statuses[0]}" if statuses else "parts:technical"
    factual = str(verdict.factual_verdict or "")
    if factual in _VERDICT_HEADLINE:
        return f"verdict:{factual}"
    return ""


def _content(presentation: FactcheckPresentation,
             verdict: CheckedVerdict | None):
    """Единая контент-модель для HTML- и plain-сериализации.

    P0-FACTCHECK-CORRECTIVE (§7.3): техническое ограничение выводится
    ОДИН раз — заголовок по reason-коду исключает второй перенос того же
    ограничения отдельной концовкой. P0-FACTCHECK-CORRECTIVE (§7.4):
    обязательная композиция тела (принудительный список 2–4 пунктов)
    снята — тело вербализатора проходит как есть."""
    technical = None
    execution_status = (str(getattr(verdict, "execution_status", "") or "")
                        if verdict is not None else "")
    execution_cause = (str(getattr(verdict, "execution_cause", "") or "")
                       if verdict is not None else "")
    if execution_status == EXECUTION_TECHNICAL_UNVERIFIED:
        # FCT-603 (S4 U3): структурный технический статус сильнее прочих
        # источников заголовка — технический сбой никогда не подаётся как
        # содержательное «Недостаточно данных для проверки». Точный
        # существующий reason-код (реестр) сохраняет приоритет; иначе —
        # человеческая причина исполнения (`execution_cause`).
        technical = (_TECHNICAL_HEADLINE.get(str(verdict.reason_code or ""))
                     or _EXECUTION_TECHNICAL_HEADLINE.get(execution_cause)
                     or _EXECUTION_TECHNICAL_FALLBACK)
    elif execution_status != EXECUTION_PARTIAL:
        # FCT-602 (S4 U3): при `partial` подтверждённые части не прячутся за
        # техническим заголовком — он остаётся содержательным, а неполнота
        # называется короткой оговоркой ниже.
        technical = (_TECHNICAL_HEADLINE.get(str(verdict.reason_code or ""))
                     if verdict is not None else None)
        if technical is None and verdict is not None:
            # Reviewer F3: технический сбой не называется «недостатком данных»
            # и когда reason-код прогона пуст (часть упала, часть ответила).
            technical = _technical_headline_from_parts(verdict)
    headline = technical or (_VERDICT_HEADLINE.get(verdict.factual_verdict)
                             if verdict is not None else None)
    links = _safe_links(presentation.links)
    if verdict is not None and verdict.evidence is not None \
            and verdict.evidence.refs:
        # §3.3: показывать можно ТОЛЬКО ссылки EvidenceMap этого прогона —
        # подмена/устаревшая ссылка в presentation не становится «источником».
        run_urls = {ref.url for ref in verdict.evidence.refs if ref.url}
        links = tuple(u for u in links if u in run_urls)
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
    # S16-FC-FINALIZE / SFC-10-06 (owner §10.6): граница пользовательской речи.
    # Служебные enum/ID/сырые контейнеры (OCR-контекст), попавшие в тело от
    # любого Writer'а, не публикуются вместо нормального ответа. Обычный текст
    # и факты не меняются (чистка идемпотентна).
    # §7.3: технический сбой объясняется явно, но ОДИН раз: при техническом
    # заголовке отдельная концовка с тем же ограничением не добавляется
    # (заголовок + абзац + концовка = три одинаковых сообщения — снято).
    technical_notice = _TECHNICAL_NOTICE.get(str(
        verdict.reason_code or "")) if verdict is not None else None
    if technical_notice and technical_notice not in notice and not technical \
            and execution_status != EXECUTION_PARTIAL:
        notice = f"{notice} {technical_notice}".strip() if notice \
            else technical_notice
    if execution_status == EXECUTION_PARTIAL:
        # FCT-602 (S4 U3): короткая и конкретная оговорка о неполноте;
        # причина — человеческая, без внутренних ID/кодов.
        cause_phrase = _PARTIAL_CAUSE_NOTICE.get(execution_cause, "")
        partial_notice = (_PARTIAL_NOTICE
                          + (f" ({cause_phrase})" if cause_phrase else "")
                          + _PARTIAL_NOTICE_SUFFIX)
        if partial_notice not in notice:
            notice = f"{notice} {partial_notice}".strip() if notice \
                else partial_notice
    if not links and not notice and verdict is not None \
            and verdict.evidence.refs:
        notice = _NO_LINKS_NOTICE
    from services.factcheck_service import strip_service_tokens
    body = strip_service_tokens(str(presentation.text or ""))
    notice = strip_service_tokens(notice)
    return headline, body, links, notice


def _trim(text: str, limit: int = _PART_TEXT_MAX_CHARS) -> str:
    """Схлопнуть пробелы и обрезать по лимиту (ТОЛЬКО служебные пометки).

    ASAP-FC-VOICE-01 / A (§5 контракта): обрезка осталась только для
    ``gap_note`` (служебная причина пробела, 120 символов). Авторские
    формулировки тезисов больше не режутся: ``_trim`` вызывается для частей
    с явным лимитом ``None``.
    """
    cleaned = " ".join(str(text or "").split())
    if limit is None or len(cleaned) <= limit:
        return cleaned
    return cleaned[:limit - 1].rstrip() + "…"


def _part_is_substantive(part) -> bool:
    return str((part or {}).get("factual_verdict") or "") in (
        "supported", "refuted", "mixed")


def _technical_statuses(verdict: CheckedVerdict | None) -> list[str]:
    """Технические статусы частей в порядке появления (без повторов)."""
    out: list[str] = []
    for part in ((verdict.parts or ()) if verdict is not None else ()):
        if not isinstance(part, dict):
            continue
        status = str(part.get("status_detail") or "")
        if status in _TECHNICAL_PART_LABELS and status not in out:
            out.append(status)
    return out


def _technical_headline_from_parts(verdict: CheckedVerdict | None) -> str | None:
    """Заголовок «Проверка не завершена: …», если содержательного разбора нет,
    а части упали технически (Reviewer F3).

    FC-04.6/FC-05.1 (corrective 05.11.2026): части, пониженные validator'ом
    (``validator_suppressed``), — не технический отказ: проверка завершилась
    содержательно, и заголовок незавершённой проверки ей не ставится."""
    if verdict is None:
        return None
    if str(verdict.factual_verdict or "") in (
            "supported", "refuted", "mixed"):
        return None
    parts = [p for p in (verdict.parts or ()) if isinstance(p, dict)]
    if any(p.get("validator_suppressed") for p in parts):
        return None
    if any(_part_is_substantive(p) for p in parts):
        return None
    statuses = _technical_statuses(verdict)
    if not statuses:
        return None
    return _TECHNICAL_STATUS_HEADLINE.get(statuses[0])


def _refs_by_id(verdict: CheckedVerdict | None) -> dict:
    if verdict is None or verdict.evidence is None:
        return {}
    return {ref.evidence_id: ref for ref in verdict.evidence.refs if ref.url}


def _publication_kind_by_url(verdict: CheckedVerdict | None) -> dict:
    """FCT-023 (S4 U3): URL → publication_kind из coverage текущего прогона.

    Источник — только уже установленные ClaimEvidence (ось U1); новых
    запросов/классификаций здесь нет. EvidenceRef этой оси не несёт, поэтому
    подпись берётся у claim-покрытия, а не угадывается по тексту.
    """
    out: dict = {}
    if verdict is None:
        return out
    for cov in (getattr(verdict, "claims", ()) or ()):
        for ev in (getattr(cov, "evidence", ()) or ()):
            url = str(getattr(ev, "url", "") or "")
            kind = str(getattr(ev, "publication_kind", "") or "")
            if url and kind in _PUBLICATION_KIND_LABELS \
                    and url not in out:
                out[url] = kind
    return out


def _source_suffix(source_kind: str, publication_kind: str = "") -> str:
    """« — пересказ, пресс-релиз — не прямое доказательство» (S4 U3).

    Подписи не выдумывают ссылок и не меняют роль evidence: публичная
    формулировка формы публикации. Для пресс-релиза/интерпретации рядом
    честная пометка — они не выглядят прямым доказательством.
    """
    bits: list[str] = []
    source_label = _SOURCE_KIND_LABELS.get(str(source_kind or ""), "")
    if source_label:
        bits.append(source_label)
    publication_label = _PUBLICATION_KIND_LABELS.get(
        str(publication_kind or ""), "")
    if publication_label and publication_label != source_label:
        if publication_kind in _NON_DIRECT_PUBLICATION_KINDS:
            bits.append(f"{publication_label} — "
                        f"{_NON_DIRECT_PUBLICATION_NOTE}")
        else:
            bits.append(publication_label)
    return f" — {', '.join(bits)}" if bits else ""


def _part_bindings(verdict: CheckedVerdict | None) -> list:
    """FC-RENDER (§3.6): (текст части, вердикт части, [EvidenceRef], gap) —
    разбор ключевых утверждений с цитатами, привязанными к каждому.
    Только URL из EvidenceMap текущего прогона (allowlist уже проверен
    сервером в verdict_from_payload).

    P0-FACTCHECK (§3.5): часть без привязки к источнику НЕ выпадает из
    разбора — иначе «неподтверждённая часть» исчезала и общий вердикт
    выглядел полным. Такая часть показывается без ссылок.

    ASAP-FC-EVIDENCE-STYLE-02 §4: ``gap`` — КОНКРЕТНАЯ причина пробела из
    retrieval-слоя (техсбой/нет источников/недоказанное число), чтобы
    публичная фраза отличала их друг от друга.

    ASAP-FC-VOICE-01 / A (§5): предела числа частей больше нет — список
    публикуется только как fallback проверенных данных, когда тела Writer'а
    фактически нет, и терять в нём тезисы нельзя.
    """
    if verdict is None:
        return []
    refs = _refs_by_id(verdict)
    out = []
    seen_texts: set[str] = set()
    for part in (verdict.parts or ()):
        if not isinstance(part, dict):
            continue
        text = str(part.get("text") or "").strip()
        if not text:
            continue
        key = text.lower()[:100]
        if key in seen_texts:
            continue
        part_refs = [refs[str(r)] for r in (part.get("evidence_refs") or ())
                     if isinstance(r, str) and str(r) in refs]
        seen_texts.add(key)
        out.append((text, str(part.get("factual_verdict") or ""), part_refs,
                    str(part.get("gap_note") or ""),
                    str(part.get("status_detail") or ""),
                    bool(part.get("unverified_media")),
                    str(part.get("media_note") or "")))
    return out


def _sources_rows(verdict: CheckedVerdict | None, links, *,
                  bound_urls: set, esc, esc_attr, html_mode: bool,
                  pub_by_url: dict | None = None
                  ) -> list[str]:
    """Строки «Источники:» с ролью каждого источника (FC-RENDER §3.6:
    никаких доменов без объяснения); ссылки, уже привязанные к частям,
    во втором списке не повторяются. FCT-023 (S4 U3): к роли добавляется
    подпись формы публикации из уже установленного evidence."""
    kind_by_url: dict = {}
    if verdict is not None and verdict.evidence is not None:
        for ref in verdict.evidence.refs:
            if ref.url and ref.url not in kind_by_url:
                kind_by_url[ref.url] = str(ref.source_kind or "")
    rows: list[str] = []
    for url in links:
        if url in bound_urls:
            continue
        publication_kind = (pub_by_url or {}).get(url, "")
        label = _safe_host(url) or "источник"
        suffix = _source_suffix(kind_by_url.get(url, ""), publication_kind)
        if html_mode:
            rows.append(f"{len(rows) + 1}. <a href=\"{esc_attr(url)}\">"
                        f"{esc(label)}</a>{esc(suffix)}")
        else:
            rows.append(f"{len(rows) + 1}. {url}{suffix}")
    return rows


def _serialize(presentation: FactcheckPresentation,
               verdict: CheckedVerdict | None, *, html_mode: bool,
               allow_critique: bool = True) -> str:
    headline, body, links, notice = _content(presentation, verdict)
    esc = _esc if html_mode else (lambda s: s)
    esc_attr = _esc_attr if html_mode else (lambda s: s)
    blocks: list[str] = []
    if headline:
        headline = str(headline)
        blocks.append(f"<b>{esc(headline)}</b>" if html_mode else headline)
    # ASAP-FC-VOICE-01 / A (§5 контракта): шаблонный раздел «Критический
    # разнос» как ФОРМАТ снят — renderer больше не вырезает критику из текста и
    # не печатает её жирным заголовком. Директива владельца действует в
    # промпте (``resolve_critique_section`` + политика), а готовый текст
    # публикуется как автор написал.
    #
    # ``allow_critique=False`` (настройка чата OFF) сохраняет детерминированную
    # гарантию: прежний формат узнается и вычищается, чтобы выключенная
    # настройка не оставляла в публикации «лишний раздел».
    body_text = str(body or "").strip()
    legacy_section = ""
    if not allow_critique:
        without_legacy, legacy_section = split_critique_section(body_text)
        if legacy_section:
            body_text = without_legacy.strip()
    # P0-FACTCHECK-CORRECTIVE (§7.4): обязательная композиция снята — тело
    # вербализатора (его собственная структура и длина) проходит как есть.
    if body_text:
        blocks.append(esc(body_text))
    # ASAP-FC-VOICE-01 / A (§5): список проверенных утверждений стал FALLBACK
    # публикацией — он выходит, только когда содержательного тела Writer'а
    # фактически нет (пустое/вырожденное тело). Так проверенный вердикт,
    # покрытие тезисов и валидированные ссылки не теряются на сбое речевой
    # фазы, но и не дублируют сказанное в обычном ответе.
    #
    # FCT-702 (S4 U3): часть с непроверенным изображением показывается ВСЕГДА —
    # оговорка принадлежит именно этой части, а не всей публикации, поэтому
    # подтверждённое текстом тело не прячет её.
    bindings_all = _part_bindings(verdict)
    if body_text:
        bindings = [b for b in bindings_all if b[5]]
    else:
        bindings = bindings_all
    pub_by_url = _publication_kind_by_url(verdict)
    if bindings:
        lines: list[str] = []
        for (text, part_verdict, part_refs, gap_note, status_detail,
             media_unverified, media_note) in bindings:
            # Reviewer F3: технический исход части называется техническим —
            # «данных недостаточно» остаётся только для реального отсутствия
            # подходящих источников/недоказанного числа.
            label = _TECHNICAL_PART_LABELS.get(status_detail) \
                or _PART_LABELS.get(part_verdict)
            cites = []
            for ref in part_refs:
                host = _safe_host(ref.url) or "источник"
                suffix = _source_suffix(ref.source_kind,
                                        pub_by_url.get(ref.url, ""))
                if html_mode:
                    cites.append(f"<a href=\"{esc_attr(ref.url)}\">"
                                 f"{esc(host)}</a>{esc(suffix)}")
                else:
                    cites.append(f"{ref.url}{suffix}")
            cites_text = ", ".join(cites)
            # §5: авторская формулировка тезиса не обрезается (лимит None).
            trimmed = _trim(text, None)
            label_part = f" — {esc(label)}" if (label and html_mode) else \
                (f" — {label}" if label else "")
            # §4: конкретная причина пробела (техсбой/нет источников/
            # недоказанное число) — рядом со СВОИМ утверждением; при
            # технической подписи тот же смысл второй раз не повторяется.
            gap = _trim(gap_note, _PART_TEXT_MAX_CHARS) if gap_note else ""
            if status_detail in _TECHNICAL_PART_LABELS and gap:
                gap = ""
            gap_part = (f" ({esc(gap)})" if html_mode else f" ({gap})") \
                if gap else ""
            # FCT-702 (S4 U3): оговорка ровно у этой части; если оркестратор
            # передал фактическую причину материала — показываем её.
            media_text = media_note or _MEDIA_PART_NOTE
            media_part = (f" ({esc(media_text)})" if html_mode
                          else f" ({media_text})") if media_unverified else ""
            body_line = esc(trimmed) if html_mode else trimmed
            if cites_text:
                line = (f"{body_line}{label_part}{gap_part}{media_part}: "
                        f"{cites_text}")
            else:
                # P0-FACTCHECK: часть без источника остаётся видимой и
                # честно помечена (не «факт без ссылки» и не выброшена).
                line = (f"{body_line}{label_part}{gap_part}{media_part} "
                        f"(проверяемой ссылки нет)")
            lines.append("• " + line)
        # §5: «…и ещё N: не показаны» удалено — тезисы не теряются молча.
        blocks.append("По утверждениям:\n" + "\n".join(lines))
    bound_urls = {ref.url for _t, _v, refs, _g, _s, _m, _n in bindings
                  for ref in refs}
    rows = _sources_rows(verdict, links, bound_urls=bound_urls,
                         esc=esc, esc_attr=esc_attr, html_mode=html_mode,
                         pub_by_url=pub_by_url)
    if rows:
        blocks.append("Источники:\n" + "\n".join(rows))
    if notice:
        blocks.append(f"<i>{esc(notice)}</i>" if html_mode else notice)
    return "\n\n".join(blocks) if blocks else esc(body_text)


# ── Публичный API ────────────────────────────────────────────────────────────

def render_factcheck(presentation: FactcheckPresentation,
                     verdict: CheckedVerdict | None = None, *,
                     allow_critique: bool = True,
                     ) -> FactcheckPresentation:
    """Детерминированный рендер → НОВАЯ FactcheckPresentation (frozen) с
    ``parse_mode="HTML"``. Структура добавляется, факты не меняются.

    ``allow_critique`` — настройка «Критический разнос» этого чата: она
    больше НЕ форматирует раздел (ASAP-FC-VOICE-01 / A §5); при ``False``
    прежний формат узнаётся и вычищается, чтобы выключенная настройка не
    оставляла в публикации лишний раздел.

    Любой сбой → та же презентация без parse_mode (plain-паритет)."""
    try:
        text = _serialize(presentation, verdict, html_mode=True,
                          allow_critique=allow_critique)
        return dataclasses.replace(presentation, text=text,
                                   parse_mode=FACTCHECK_PARSE_MODE)
    except Exception:
        logger.warning("[factcheck_v2] renderer failed — plain passthrough",
                       exc_info=True)
        return dataclasses.replace(presentation, parse_mode=None)


def render_plain(presentation: FactcheckPresentation,
                 verdict: CheckedVerdict | None = None, *,
                 allow_critique: bool = True,
                 ) -> FactcheckPresentation:
    """Plain-деградация (06E.6): та же контент-модель без разметки."""
    return dataclasses.replace(
        presentation,
        text=_serialize(presentation, verdict, html_mode=False,
                        allow_critique=allow_critique),
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
                            reply_to_message_id: int | None = None
                            ) -> int | None:
    """Доставка презентации: СУЩЕСТВУЮЩИЙ ``send_chunked_reply`` (общая
    функция НЕ меняется). С HTML — pre-split entity-safe чанков, reply
    только у первой части; TelegramBadRequest парсинга → деградирует
    ТОЛЬКО сломанный чанк (в plain), остальные идут как есть.

    UR-23.4: возвращает message_id ПЕРВОЙ фактически доставленной части
    (или None — не доставлено ничего) — для durable ledger по реальному id.
    Сама доставка байт-в-байт прежняя."""
    if not presentation.parse_mode:
        return await send_chunked_reply(bot, chat_id, presentation.text,
                                        reply_to_message_id)
    rid = reply_to_message_id
    first_id: int | None = None
    for chunk in split_entity_safe(presentation.text, _CHUNK_LIMIT):
        try:
            part_id = await send_chunked_reply(bot, chat_id, chunk, rid,
                                               parse_mode=presentation.parse_mode)
        except TelegramBadRequest:
            logger.warning("[factcheck_v2] HTML chunk failed — plain "
                           "degradation | chat=%s", chat_id, exc_info=True)
            part_id = await send_chunked_reply(bot, chat_id, visible_text(chunk), rid)
        if first_id is None:
            first_id = part_id
        rid = None
    return first_id
