"""ASAP-4 волна C (epic `asap-4-embedding-graphrag-cover-runtime`) — Legacy
full-window + source coverage (spec §3 C.3/C.4, ADR-1028-7 D7.3; T-4424/
T-4425; ТЗ §55/§56/§57/§58, §50.37).

Прод-болезнь: Legacy-фолбэк молча останавливал сборку ``<chat_history>`` на
жёстком капе (`XML context: hard cap 50000 chars reached, stopping at 307
messages`) при source 688 — окно саммари терялось без следа (§55/§56).

Контракт (вариант ARCH, ADR D7.3 — «reuse full-window semantic package»):

  * малые окна (плоский XML полностью влезает в капы) → плоский
    ``<chat_history>`` бит-в-бит (поведение и формат прежние);
  * большие окна → Legacy получает иерархически свёрнутый пакет: тот же
    semantic package, что уже построен для L2 (Level-3 из Hybrid), а при
    его отсутствии — детерминированный full-window пакет
    (``build_fallback_package``: chronology = ВСЕ сообщения, fragments с
    авторским контекстом + hierarchical reduction budget'ом);
  * coverage честный (§57): target ``source_coverage=100%``; если реально
    меньше — run помечается degraded coverage (WARN + событие
    ``SUMMARY_COVERAGE_DEGRADED`` + поле в run state), НЕ молча;
  * ``MAX_SUMMARY_PARTS`` не трогается (§58) — только выходные
    Telegram-части, НЕ input coverage cap;
  * source normalization смысл не меняет, алгоритмическая предфильтрация
    ASAP-2.1 НЕ восстанавливается (§50.38/R4-D-038): пакет теряет контент
    только бюджетом, и каждая потеря видна в coverage-метриках (§50.37).

Чистый модуль (0 LLM, без БД; hot/env-резолв капов). Δ DDL = 0.

Kill-switch ``SUMMARY_LEGACY_FULL_WINDOW_ENABLED`` (env, default ON):
OFF → прежний тихий XML 50k hard stop (бит-в-бит).
"""
from __future__ import annotations

import json
import logging

from config.settings import settings

logger = logging.getLogger(__name__)


# ── Kill-switch (spec §8.2) ────────────────────────────────────────────────

def legacy_full_window_enabled() -> bool:
    """``SUMMARY_LEGACY_FULL_WINDOW_ENABLED`` (env-only, default ON; резолв
    per-call, никогда не бросает). OFF → прежний XML hard stop."""
    try:
        return bool(getattr(settings, "SUMMARY_LEGACY_FULL_WINDOW_ENABLED",
                            True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


# ── ASAP 4.1 волна 3 (T-4611, spec §3; ADR-1028-8 D7 EXTEND) ───────────────

def legacy_source_window_enabled() -> bool:
    """Kill-switch ``SUMMARY_LEGACY_SOURCE_WINDOW_ENABLED`` (env-only,
    default ON; резолв per-call, никогда не бросает). OFF → контур Legacy
    full-window 2.58.46 (включая действующие капы окна) байт-в-бит."""
    try:
        return bool(getattr(settings, "SUMMARY_LEGACY_SOURCE_WINDOW_ENABLED",
                            True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def snapshot_rows(window) -> list | None:
    """Durable SummarySourceWindow → строки окна, совместимые с
    потребителями Legacy (XmlGroundingBuilder/LLM-контент): поля
    id/tg_message_id/timestamp/user_id/author_name/text/reply_to_id/
    media_type/is_forward/forward_source. Материал — ТОТ ЖЕ snapshot run'а
    (единый источник с Hybrid, source_ref); fail-open к переданным rows —
    вызывающий контур. Никогда не бросает."""
    if window is None:
        return None
    try:
        rows: list = []
        for message in window.messages_as_view():
            if not isinstance(message, dict):
                continue
            row = {
                "id": message.get("db_id"),
                "tg_message_id": message.get("message_id"),
                "timestamp": message.get("timestamp"),
                "user_id": message.get("author_id"),
                "author_name": message.get("display_name"),
                "text": message.get("text"),
                "reply_to_id": message.get("reply_to_message_id"),
                "media_type": message.get("media_type"),
                "is_forward": 1 if message.get("is_forward") else 0,
                "forward_source": message.get("forward_source"),
            }
            if row["id"] is None and row["tg_message_id"] is None:
                continue
            rows.append(row)
        return rows or None
    except Exception:      # pragma: no cover - защитная ветка
        logger.warning("legacy source window: snapshot_rows failed",
                       exc_info=True)
        return None


async def load_legacy_rows(db, run_id) -> list | None:
    """Строки окна run'а из durable SourceWindow (source_ref; T-4611).
    ``None`` — snapshot недоступен (fail-open к переданным rows)."""
    try:
        from services import summary_source_window as ssw
        window = await ssw.load_source_window(db, run_id)
        return snapshot_rows(window)
    except Exception:      # pragma: no cover - защитная ветка
        logger.warning("legacy source window: load failed | run_id=%s",
                       run_id, exc_info=True)
        return None


# ── Капы окна (те же ключи, что читает XmlGroundingBuilder.build) ──────────

def resolve_window_caps(hot_get=None) -> tuple[int, int]:
    """``(max_messages, max_chars)`` — hot → env (те же ключи, что
    ``summary_xml``): ``limits.summary_max_window_messages`` /
    ``limits.summary_max_context_chars``. Никогда не бросает."""
    if hot_get is None:
        from services import hot_config as hot
        hot_get = hot.get
    try:
        max_messages = int(hot_get(
            "limits.summary_max_window_messages",
            settings.SUMMARY_MAX_WINDOW_MESSAGES))
    except (TypeError, ValueError):      # pragma: no cover - защитная ветка
        max_messages = int(settings.SUMMARY_MAX_WINDOW_MESSAGES)
    try:
        max_chars = int(hot_get(
            "limits.summary_max_context_chars",
            settings.SUMMARY_MAX_CONTEXT_CHARS))
    except (TypeError, ValueError):      # pragma: no cover - защитная ветка
        max_chars = int(settings.SUMMARY_MAX_CONTEXT_CHARS)
    return max_messages, max_chars


def xml_built_count(xml_context: str) -> int:
    """Сколько сообщений фактически вошло в плоский XML (элемент
    ``<message `` на каждую строку окна)."""
    return str(xml_context or "").count("<message ")


def flat_fits(xml_context: str, source_total: int) -> bool:
    """Плоский XML покрыл ВСЁ окно (ни капа сообщений, ни капа символов не
    сработал) → малое окно, бит-в-бит прежний путь."""
    source_total = max(0, int(source_total or 0))
    if source_total == 0:
        return True
    return xml_built_count(xml_context) >= source_total


# ── Coverage источника (§50.37, §57; R17-safe числа) ───────────────────────

def compute_package_coverage(package, source_total: int) -> dict:
    """Coverage-метрики пакета против source-окна (§50.37): сколько
    сообщений окна ПРЕДСТАВЛЕНО (chronology ∪ fragments ∪ evidence ∪
    unassigned). Каждая потеря видима числом, без текстов.

    ASAP-4 волна D (T-4433, §50.32): coverage map дополняется
    ``major_topics_total/represented`` и ``unique_events_total/represented``
    (internal, в Analytics — publication/coverage), детерминированно:
      * major topics — темы пакета; ``total`` = представленные + слитые
        редукцией (service.reduction_topics_merged, 0 на fallback-пакете);
      * unique events — дедуплицированные факты (нормализованный text);
        ``total`` = представленные + слитые редукцией
        (service.reduction_facts_merged).
    """
    considered_ids: set = set()
    threads = package.get("threads") if isinstance(package, dict) else None
    fact_keys: set = set()
    for thread in threads or []:
        if not isinstance(thread, dict):
            continue
        for entry in thread.get("chronology") or []:
            if isinstance(entry, dict) and isinstance(
                    entry.get("message_id"), int):
                considered_ids.add(entry["message_id"])
        for fragment in thread.get("fragments") or []:
            if isinstance(fragment, dict) and isinstance(
                    fragment.get("message_id"), int):
                considered_ids.add(fragment["message_id"])
        for fact in thread.get("facts") or []:
            if isinstance(fact, dict):
                for eid in fact.get("evidence_message_ids") or []:
                    if isinstance(eid, int):
                        considered_ids.add(eid)
                text = str(fact.get("text") or "").strip().casefold()
                if text:
                    fact_keys.add(text)
        for eid in thread.get("evidence_ids") or []:
            if isinstance(eid, int):
                considered_ids.add(eid)
    for mid in (package or {}).get("unassigned_message_ids") or []:
        if isinstance(mid, int):
            considered_ids.add(mid)
    total = max(0, int(source_total or 0))
    considered = len(considered_ids)
    coverage = 100.0 if total == 0 else min(
        100.0, round(100.0 * considered / total, 2))
    # §50.32: coverage map тем/событий (internal metadata пакета).
    service = (package or {}).get("service") if isinstance(package, dict) \
        else None
    topics_merged = facts_merged = 0
    if isinstance(service, dict):
        try:
            topics_merged = max(0, int(service.get(
                "reduction_topics_merged") or 0))
        except (TypeError, ValueError):
            topics_merged = 0
        try:
            facts_merged = max(0, int(service.get(
                "reduction_facts_merged") or 0))
        except (TypeError, ValueError):
            facts_merged = 0
    major_topics_represented = len([t for t in threads or []
                                    if isinstance(t, dict)])
    unique_events_represented = len(fact_keys)
    return {
        "source_messages_total": total,
        "source_messages_considered": considered,
        "dropped": max(0, total - considered),
        "coverage_percent": coverage,
        "major_topics_total": major_topics_represented + topics_merged,
        "major_topics_represented": major_topics_represented,
        "unique_events_total": unique_events_represented + facts_merged,
        "unique_events_represented": unique_events_represented,
    }


# ── Контент Legacy для большого окна (ADR D7.3) ────────────────────────────

_FULL_WINDOW_HEADER = (
    "ИСТОРИЯ ЧАТА (полное окно; иерархически свёрнутый пакет: темы, "
    "хронология и исходные сообщения с авторами; служебные поля не "
    "передаются):")


def build_legacy_package_content(package) -> str:
    """Детерминированный user-контент Legacy для полного окна: тот же
    формат секций, что L2-вход (compact JSON, фиксированный порядок ключей),
    но с Legacy-заголовком (system-канон R11 не меняется). Без length-блока
    (длина Legacy статьи определяется промптом ``{max_symbols}``).
    ``unassigned_message_ids`` сериализуются (сообщения окна вне тем — часть
    полного окна, coverage честен)."""
    content = {"schema_version": 2, "threads": [],
               "unassigned_message_ids": [
                   mid for mid in (package or {}).get(
                       "unassigned_message_ids") or []
                   if isinstance(mid, int)]}
    for thread in (package or {}).get("threads") or []:
        if not isinstance(thread, dict):
            continue
        chronology = []
        for entry in thread.get("chronology") or []:
            if isinstance(entry, dict):
                chronology.append({
                    "message_id": entry.get("message_id"),
                    "timestamp": entry.get("timestamp"),
                    "topic_ids": list(entry.get("topic_ids") or []),
                })
        facts = []
        for fact in thread.get("facts") or []:
            if isinstance(fact, dict):
                facts.append({
                    "text": fact.get("text"),
                    "evidence_message_ids": list(
                        fact.get("evidence_message_ids") or []),
                })
        fragments = []
        for fragment in thread.get("fragments") or []:
            if isinstance(fragment, dict):
                fragments.append({
                    "message_id": fragment.get("message_id"),
                    "author_id": fragment.get("author_id"),
                    "display_name": fragment.get("display_name"),
                    "timestamp": fragment.get("timestamp"),
                    "reply_to_id": fragment.get("reply_to_id"),
                    "text": fragment.get("text"),
                })
        content["threads"].append({
            "thread_id": thread.get("thread_id"),
            "name": thread.get("name"),
            "description": thread.get("description"),
            "chronology": chronology,
            "facts": facts,
            "fragments": fragments,
        })
    body = json.dumps(content, ensure_ascii=False, separators=(",", ":"))
    return _FULL_WINDOW_HEADER + "\n" + body


# ── Логи (аддитивные, R17-safe: только числа/коды) ─────────────────────────

def log_full_window(*, run_id, chat_id, mode, source_total, considered,
                    coverage_percent, content_tokens=None) -> None:
    logger.info(
        "LEGACY_FULL_WINDOW | run_id=%s | chat_id=%s | mode=%s | "
        "source_messages=%d | considered=%d | coverage=%.2f%% | "
        "content_tokens=%s",
        run_id or "none", chat_id, mode or "-", source_total, considered,
        coverage_percent,
        str(content_tokens) if content_tokens is not None else "-")


def log_coverage_degraded(*, run_id, chat_id, source_total, considered,
                          coverage_percent, reason) -> None:
    logger.warning(
        "LEGACY_COVERAGE_DEGRADED | run_id=%s | chat_id=%s | "
        "source_messages=%d | considered=%d | coverage=%.2f%% | reason=%s",
        run_id or "none", chat_id, source_total, considered,
        coverage_percent, reason or "-")
