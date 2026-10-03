"""Epic 24/25 — SummaryGenerator: full summary pipeline (Sections 33.7 + 34.3).

L3 compress → L1 window → XML → L2 RAG → L3 vectors → LLM → postprocessing
(shiz postfix, 4096-chunking with TelegramRetryAfter handling) → send.

Epic 25 (B2/B4/B5): `generate_and_send(chat_id, manual=False)` — manual calls
(/summary) get UX replies for empty window and busy slot; cron stays quiet
(no ack, no empty-window UX, INFO logs instead). Error UX (R13) is sent to both.

Раунд N (T-841): глобальный asyncio.Lock (A5) заменён на per-chat пул
services/smartmodule_concurrency — чат A больше не блокирует чат B; в одном
чате до limits.smartmodule_concurrency_per_chat параллельных саммари (крон и
ручной /summary ходят через пул по chat_id). Busy-семантика B5 сохранена:
manual при занятом чате получает _UX_BUSY и встаёт в очередь, крон молчит
(INFO «summary: lock busy — queued»).
"""
import asyncio
import dataclasses
import logging
import os
import re
import sqlite3
import time
from functools import lru_cache

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from config.settings import settings
from services import hot_config as hot
from services.canonical_context import format_context_item
from services.chat_params import (
    get_chat_param as _chat_limit,  # G-3 per-chat
)
from services.database import row_get
from services.llm_client import LLMBadResponseError, LLMError, LLMTimeoutError
from services import anticliche_cache
from services import usage_events
from services.negative_constraints import (
    DEFAULT_ENABLED_RULES,
    channel_enabled_rules,
    verbalize_validated,
)
from services.prompt_style_blocks import (
    compose_verbalizer_system,
    resolve_prompt,
)
from services.summary_cleanup import cleanup_llm_text
from services.summary_memory import _build_batch_text, fire_and_forget
from services.summary_prompts import (
    PREV_SUMMARY_NARRATOR_R1023,
    SUMMARY_COVER_STYLE_DEFAULT,
    SUMMARY_EDITOR_SYSTEM_PROMPT,
    SUMMARY_NARRATOR_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
)
# S7 (ADR-1026-9 D1/D2/D6): сквозной `run_id` + события жизненного цикла §108.
# S6 (ADR-1026-11 D5/D6): §106-коды + публикационные события PUBLISH_*.
from services.summary_run_log import (
    CODE_COVER_GENERATION_FAILED,
    CODE_RICH_MESSAGE_SEND_FAILED,
    CODE_SUMMARY_GENERATION_FAILED,
    CODE_TEXT_FALLBACK_FAILED,
    STATUS_DEGRADED,
    STATUS_EMPTY,
    STATUS_FAILED,
    STATUS_OK,
    RunContext,
    attempts_of,
    finish_run,
    http_status_of,
    log_cover_complete,
    log_cover_error,
    log_cover_start,
    log_format_complete,
    log_format_error,
    log_format_start,
    log_publish_rich_complete,
    log_publish_rich_error,
    log_publish_rich_start,
    log_publish_text_complete,
    log_publish_text_error,
    log_publish_text_start,
    log_summary_start,
    provider_host,
)
from services.system2_handoff import (
    normalize_cover_prompt,
    parse_summary_handoff_ex,
)
from services.external_log import log_external_api
from services.image_generation import (
    generate_image_verbose,
    provider_label,
    reason_class,
)
from services.smartmodule_concurrency import get_smartmodule_concurrency_pool
# ASAP-2 §11 (контракт (g)): единая точка Hybrid-бюджета для режима фильтра.
from services.summary_hybrid_budget import resolve_hybrid_context_budget
from services.summary_xml import escape_xml_text
from services.telegram_send import (
    SUMMARY_COVER_MEDIA_ID,
    build_cover_media,
    edit_text_safe,
    looks_rich,
    send_rich_message,
    send_text,
)
from services.token_counter import (
    count_tokens,
    resolve_chat_limit,
    resolve_context_tokens,
    safe_budget,
    truncate_to_tokens,
)
from services.typing_manager import typing_active

try:
    import aiosqlite
    _SQLITE_ERRORS = (sqlite3.Error, aiosqlite.Error)
except ImportError:  # pragma: no cover
    _SQLITE_ERRORS = (sqlite3.Error,)

logger = logging.getLogger(__name__)

# Токенный потолок контекста Саммари при незаданном значении (F4/64.7).
# Согласован с `resolve_chat_limit(..., 30000, ...)` в `_run` и с
# `resolve_context_tokens` (L-R1026S1-1): `0`/`None` → этот дефолт, `-1` → потолок
# «безлимита». Единая точка, чтобы нарезка/бюджет §93 не вырождались.
_SUMMARY_CONTEXT_TOKEN_DEFAULT = 30000


# ── ASAP-2 §1/D5 (контракт (d)): send-time кап Legacy-доставки ─────────────
# `limits.max_summary_parts` — ЕДИНСТВЕННАЯ семантика: максимальное число
# Telegram sendMessage-частей, на которые можно разбить ДЛИННЫЙ legacy-
# саммари (prompt-бюджет parts×4000−200 + кап числа чанков). Hybrid-контур
# кап не получает (`max_chunks=None` — §105 plain-доставка полного текста);
# rich-путь капом НЕ ограничен (sendRichMessage ≠ sendMessage). Избыток НЕ
# теряется молча: WARN `LEGACY_CHUNKS_CAPPED` (R17-safe числа).

def resolve_legacy_max_parts() -> int:
    """Резолв parts (hot `limits.max_summary_parts` → env): ≥1."""
    try:
        value = int(hot.get("limits.max_summary_parts",
                            settings.MAX_SUMMARY_PARTS))
    except (TypeError, ValueError):
        value = int(getattr(settings, "MAX_SUMMARY_PARTS", 1) or 1)
    return max(1, value)


# ── ASAP-4 волна D (T-4431/T-4432, ADR-1028-7 D3/D5) ───────────────────────

def _l2_review_enabled_safe() -> bool:
    """Kill-switch ``SUMMARY_L2_REVIEW_ENABLED`` (spec §8.2): OFF → прежний
    single-call L2 (бит-в-бит, модуль review не импортируется). Никогда не
    бросает (fail → OFF = legacy)."""
    try:
        return bool(getattr(settings, "SUMMARY_L2_REVIEW_ENABLED", True))
    except Exception:      # pragma: no cover - защитная ветка
        return False


def _l2_review_extra_calls(l2_result) -> int:
    """Число логических review/revision-вызовов L2-стадии (R17-счётчик
    ``calls_so_far``; бюджет ≤6 закреплён в review-модуле)."""
    try:
        metrics = getattr(l2_result, "metrics", None) or {}
        return (int(metrics.get("l2_review_calls", 0) or 0)
                + int(metrics.get("l2_revision_calls", 0) or 0))
    except Exception:      # pragma: no cover - защитная ветка
        return 0


def _cap_legacy_chunks(chunks, max_chunks, *, run_id=None, chat_id=None):
    """Первые ``max_chunks`` чанков legacy-plain; при обрезке — WARN."""
    if max_chunks is None or len(chunks) <= max_chunks:
        return chunks
    logger.warning(
        "LEGACY_CHUNKS_CAPPED | run_id=%s | chat_id=%s | chunks_total=%d | "
        "chunks_sent=%d", run_id or "none", chat_id, len(chunks),
        max_chunks)
    return chunks[:max(0, int(max_chunks))]


# ── ASAP 4.1 волна 3 (зона B/C; T-4608/T-4609/T-4610/T-4611; ADR-1028-8
# D3/D4) — kill-switches зоны B/C (env-only, default ON; резолв per-call;
# никогда не бросают — прецедент `_l2_review_enabled_safe`). ─────────────────

def _writer_source_input_enabled() -> bool:
    """Kill-switch ``SUMMARY_WRITER_SOURCE_INPUT_ENABLED`` (spec §2 B.3).
    OFF → Writer FactPackage-центричный вход (бит-в-бит 2.58.46)."""
    try:
        return bool(getattr(settings, "SUMMARY_WRITER_SOURCE_INPUT_ENABLED",
                            True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def _source_window_ids(payload_items) -> set:
    """TG message_id всего окна (id-space для ReviewResult против
    оригинала; R6-B-007; T-4610)."""
    ids = set()
    for item in payload_items or []:
        if isinstance(item, dict):
            mid = item.get("message_id")
            if isinstance(mid, int) and not isinstance(mid, bool):
                ids.add(mid)
    return ids


def _legacy_source_window_enabled() -> bool:
    """Kill-switch ``SUMMARY_LEGACY_SOURCE_WINDOW_ENABLED`` (spec §3).
    OFF → контур Legacy full-window 2.58.46 (включая действующие капы
    окна), байт-в-бит."""
    try:
        return bool(getattr(settings, "SUMMARY_LEGACY_SOURCE_WINDOW_ENABLED",
                            True))
    except Exception:      # pragma: no cover - защитная ветка
        return True


def _legacy_split_delivery_enabled() -> bool:
    """T-4611 (spec §3/§33): ON-ветка зоны C — split delivery БЕЗ потери
    tail (``MAX_SUMMARY_PARTS`` остаётся soft target промпта, а не
    усечением выдачи)."""
    return _legacy_source_window_enabled()


def _chain_tg_id(item_id) -> int | None:
    """Telegram id из канонического ``item_id`` (``tg:<id>``); иначе None."""
    if not item_id or not isinstance(item_id, str) or not item_id.startswith("tg:"):
        return None
    try:
        return int(item_id[3:])
    except (TypeError, ValueError):
        return None

# Раунд 10.23 (F6, ADR-1023-6): прежний жёсткий кап (историческое имя —
# используется тестами 10.23 как справка). Раунд 10.24 (F12/ADR-1024-4 D2):
# общий кап вынесен в env-only `SUMMARY_COVER_PROMPT_MAX_CHARS` (1000), а
# кап стиля — в `SUMMARY_COVER_STYLE_MAX_CHARS` (500).
COVER_IMAGE_PROMPT_MAX = 300


@dataclasses.dataclass
class SummaryDraft:
    """Результат System 2 саммари (Stage-1 → Stage-2).

    F6 (additive): ``cover_prompt`` — визуальный промпт обложки того же JSON
    Stage-1; ``response_mode`` — роутер режимов F3. Число LLM-вызовов не растёт.
    S6 (ADR-1026-11 D2, additive): ``title`` — заголовок из digest Stage-1
    (``extract_title_from_markdown``, 0 LLM) для настоящего ``<h1>`` rich-пути.
    """

    text: str
    cover_prompt: str = ""
    # F6 (10.24, ADR-1024-10 D3): ``""`` = режим не выбран (сбойный путь) —
    # fallback-ключ резолвится в compose, без второго источника дефолта.
    response_mode: str = ""
    # S6 (10.26, ADR-1026-11 D2): заголовок digest; ``""`` → fallback-приоритет
    # §5.3 в адаптере/документе (выдуманный заголовок запрещён).
    title: str = ""


def compose_cover_image_prompt(style: str | None, cover_prompt: str) -> str:
    """«Стиль обложки» + visual prompt (F12/ADR-1024-4 D2, AMEND 1023-6).

    Стиль сохраняется ПРИОРИТЕТНО (до своего капа
    `SUMMARY_COVER_STYLE_MAX_CHARS`), visual добирает остаток до общего капа
    `SUMMARY_COVER_PROMPT_MAX_CHARS`; при переполнении режется visual, а не
    стиль (инструкция владельца типа «PERMsoc» обязана дойти до модели)."""
    style_cap = int(getattr(settings, "SUMMARY_COVER_STYLE_MAX_CHARS", 500))
    total_cap = int(getattr(settings, "SUMMARY_COVER_PROMPT_MAX_CHARS", 1000))
    s = (style or "").strip()[:max(0, style_cap)]
    remaining = total_cap - len(s) - 1
    v = (cover_prompt or "").strip()[:max(0, remaining)]
    return " ".join(part for part in (s, v) if part)


def resolve_cover_style(value) -> str:
    """T-2509 (hotfix4, ADR-1025-8 D1): эффективный «Стиль обложки».

    Настроенный владельцем стиль применяется как есть; код-дефолт — ТОЛЬКО
    когда значение реально отсутствует или пусто (``None``/пробелы). Гарантия:
    потеря «стиля владельца» не превращается в пустой стиль, а честно
    откатывается к дефолту."""
    if value is None:
        return SUMMARY_COVER_STYLE_DEFAULT
    text = value if isinstance(value, str) else str(value)
    return text.strip() or SUMMARY_COVER_STYLE_DEFAULT


def cover_style_markers(style: str) -> dict:
    """T-2508 (hotfix4, R17): маркеры содержимого стиля — БЕЗ самого текста.

    * ``has_comic`` — стиль требует комикс-подачу;
    * ``has_heading`` — явно задан короткий заголовок
      (``heading``/``title``/``PERMsoc``/«заголовок»);
    * ``style_is_default`` — доехал код-дефолт (настроенный стиль НЕ пришёл).

    Review L10.25H4-3: токены заголовка — по ГРАНИЦАМ СЛОВ (``\\bpermsoc\\b``,
    ``\\bheading\\b``, ``\\btitle\\b``) + «заголов» (рус.), чтобы не ловить
    ложные подстроки («permanent», «permission», «entitled»).
    """
    text = (style or "").lower()
    has_heading = bool(re.search(r"\b(?:permsoc|heading|title)\b", text)) \
        or "заголов" in text
    return {
        "has_comic": "comic" in text,
        "has_heading": has_heading,
        "style_is_default": (style or "").strip() == SUMMARY_COVER_STYLE_DEFAULT,
    }


@lru_cache(maxsize=1)
def _rich_media_supported() -> bool:
    """Поддержка rich-обложек: поле ``media`` у ``InputRichMessage`` + метод
    ``Bot.send_rich_message``. aiogram < 3.30 → ``False`` (тихий plain).

    Review iter1 (Low-4): результат кэшируется на процесс (spec §3.4) —
    ``aiogram``/его типы за рантайм не меняются. Тесты сбрасывают
    ``_rich_media_supported.cache_clear()``."""
    try:
        from aiogram import Bot
        from aiogram.types import InputRichMessage
        if not hasattr(Bot, "send_rich_message"):
            return False
        fields = getattr(InputRichMessage, "model_fields", None)
        if fields is None:
            fields = getattr(InputRichMessage, "__annotations__", None) or {}
        try:
            return "media" in fields
        except TypeError:                 # pragma: no cover - defensive
            return False
    except Exception:                     # pragma: no cover - defensive
        return False


def _package_content_empty(package_result) -> bool:
    """ASAP-3.1 incident fix 29.09.2026 (EMPTY-PACKAGE GUARD): пакет пуст ПО
    МАТЕРИАЛУ — 0 fragments и 0 chronology-сообщений.

    Используется как delivery-гейт: такой пакет при непустом source window
    НЕ передаётся в L2 как обычный саммари (L2 опубликовал бы мета-текст
    «пакет пуст») — вызывающий контур уходит в LEVEL-3 Legacy."""
    metrics = getattr(package_result, "metrics", None) or {}
    try:
        fragments = int(metrics.get("fragments_count", 0) or 0)
        chronology = int(metrics.get("messages_count", 0) or 0)
    except (TypeError, ValueError):         # pragma: no cover - defensive
        return False
    return fragments == 0 and chronology == 0


_MD_TABLE_SEP_RE = re.compile(
    r"^\s*\|?(?:\s*:?-{2,}:?\s*\|)+(?:\s*:?-{2,}:?\s*)?\|?\s*$")
_MD_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+", re.MULTILINE)
_MD_FENCE_RE = re.compile(r"^\s*```.*$", re.MULTILINE)
_STRUCT_HTML_TAG_RE = re.compile(
    r"</?(?:table|thead|tbody|tr|td|th|h[1-6]|ul|ol|li|div|span|p|br|"
    r"blockquote|pre|code|strong|em|b|i)\b[^>]*>",
    re.IGNORECASE,
)


def downgrade_rich_to_plain(text: str) -> str:
    """Детерминированный даунгрейд rich → R11-plain (тихий фолбэк Article).

    Снимает структурную разметку: HTML-теги, Markdown-таблицы (separator +
    pipe-строки → plain), заголовки/фенсы/эмфазис. Слова-сущности не режутся
    (никаких `fact:`/`msg:` regex-резов)."""
    source = str(text or "")
    if not source:
        return source
    source = _MD_FENCE_RE.sub("", source)
    source = _STRUCT_HTML_TAG_RE.sub(" ", source)
    lines: list[str] = []
    for line in source.splitlines():
        if _MD_TABLE_SEP_RE.match(line):
            continue
        stripped = line.strip()
        if (stripped.startswith("|") and stripped.endswith("|")
                and "|" in stripped[1:-1]):
            cells = [cell.strip() for cell in stripped.strip("|").split("|")]
            line = " - ".join(cell for cell in cells if cell)
        lines.append(line)
    out = "\n".join(lines)
    out = _MD_HEADING_RE.sub("", out)
    out = out.replace("**", "").replace("__", "").replace("`", "")
    out = re.sub(r"\n{3,}", "\n\n", out)
    return out.strip()


def _apply_focus(user_content: str, focus: str | None) -> str:
    """Epic 65 (pure): «/summary про X» → <focus> блок в начало user_content.
    System-промпт R11 не трогаем — инструкция живёт в user-контенте."""
    if not focus or not focus.strip():
        return user_content
    from services.summary_xml import escape_xml_text   # локально — без циклов
    safe = escape_xml_text(focus.strip()[:200])
    return ('<focus note="главная тема этой выжимки — подсвети в саммари всё, '
            'что касается неё; остальное кратко">' + safe + "</focus>\n\n"
            + user_content)


def _strip_safe_html(text: str) -> str:
    """Review iter1 (H2): саммари-канал не рендерит HTML — whitelist-теги
    (`<b>`, `<i>` и пр.) срезаются, чтобы не утечь сырыми. Ленивый импорт —
    `smartmodule_utils` сам импортирует `SummaryGenerator` (цикл на уровне
    модулей недопустим)."""
    try:
        from services.smartmodule_utils import strip_lore_html
        return strip_lore_html(text)
    except Exception:  # pragma: no cover - defensive (не ломаем саммари)
        logger.warning("summary: html strip unavailable — text kept as-is")
        return text


_UX_LLM_FAILED = "не смог сделать саммари потому что упал апи"
_UX_DB_FAILED = "база данных подавилась"
_UX_GENERIC_FAILED = "не смог сделать саммари"
_UX_EMPTY = "тут тишина, саммарить нечего"        # B4: пустое окно L1, только manual
_UX_BUSY = "уже делаю саммари, подожди"          # B5: lock занят, только manual


def _elapsed_since(started) -> float | None:
    """Монотонная длительность с метки старта (S8: формат-метрика §112).

    ``None`` при отсутствии метки — честное «Нет данных», не выдуманный 0.
    """
    try:
        return (time.perf_counter() - started) * 1000.0 if started else None
    except Exception:  # pragma: no cover - защитная ветка
        return None


def _generation_code(stage: str | None) -> str | None:
    """§106/D5: код ``SUMMARY_GENERATION_FAILED`` для этапов генерации.

    L1/пакет/L2 (ON) и ``run`` (OFF, явно в call-site) — генерация; ``deliver``
    и ``db`` — не классы §106 (свой код у публикации/БД-сбоя нет).
    """
    return (CODE_SUMMARY_GENERATION_FAILED
            if stage in ("l1", "package", "l2", "run") else None)


# ASAP-2.1 (контракт (e)/T-3979): «главный шиз» — семантическое решение LLM.
# Символы алгоритмического выбора (ensure-shiz-postfix / most-active-author /
# @-regex) УДАЛЕНЫ из responsibility кода. Константа ниже — ТОЛЬКО strip-
# защита в `_derive_fallback_cover_prompt`: модель может написать шутку в
# тексте — в visual-промпт обложки она попасть не должна.
_SHIZ_MARKER = "самым главным шизом объявляется"

_KEYWORD_RE = re.compile(r"[а-яёa-z0-9]{3,}", re.IGNORECASE)

_STOPWORDS = frozenset({
    "ёпта", "ну", "и", "а", "в", "во", "на", "с", "со", "не", "что", "как",
    "это", "этот", "эта", "это", "по", "из", "от", "до", "за", "у", "о", "об",
    "к", "ко", "же", "бы", "ли", "то", "он", "она", "они", "я", "ты", "мы",
    "вы", "мне", "тебе", "да", "нет", "так", "там", "тут", "ещё", "уже",
    "все", "всё", "для", "про", "или", "но", "если", "когда", "только",
    "очень", "просто", "какой", "какая", "кого", "кому",
})


class SummaryGenerator:
    """Runs the whole summary pipeline; per-chat pool of permits (T-841)
    вместо глобального asyncio.Lock (A5) — разные чаты параллельны."""

    def __init__(self, memory, xml, llm, bot, aliases=None,
                 concurrency_pool=None) -> None:
        self.memory = memory
        self.xml = xml
        self.llm = llm
        self.bot = bot
        self.aliases = aliases
        self._pool = (concurrency_pool if concurrency_pool is not None
                      else get_smartmodule_concurrency_pool())

    async def generate_and_send(self, chat_id: int, manual: bool = False,
                                focus: str | None = None,
                                trigger_message_id: int | None = None) -> None:
        """Entrypoint for /summary (manual=True) and cron (manual=False). B2/B5.
        Epic 65: focus — тема из «/summary про X» (None = обычное саммари).
        Раунд N (T-841): слот пула per-chat; занят → busy-фраза (manual) +
        лог, затем очередь (как раньше у глобального лока B5).
        Раунд 10.23 (F1, ADR-1023-1): trigger_message_id — Telegram id
        сообщения-команды /summary (маркировка в истории); None (авто-крон)
        → legacy-путь без маркера."""
        # Проба без ожидания: занят ли слот этого чата (B5-семантика).
        permit = await self._pool.try_acquire(chat_id, timeout=0.0)
        if permit is None:
            if manual:
                await self._send_ux(chat_id, _UX_BUSY)          # B5: не стоять молча
            logger.info(
                "summary: lock busy — queued | chat_id=%s manual=%s", chat_id, manual
            )
            # Очередь, как раньше async with lock (без таймаута).
            permit = await self._pool.acquire(chat_id)
        try:
            await self._run(chat_id, manual, focus, trigger_message_id)
        finally:
            permit.release()

    async def _run(self, chat_id: int, manual: bool, focus: str | None = None,
                   trigger_message_id: int | None = None) -> None:
        # F7 (ADR-1023-7 D4): один сквозной id на саммари.
        # S7 (ADR-1026-9 D1): он же формальный `run_id` — второй id не вводим.
        correlation_id = usage_events.new_correlation_id()
        # ── ASAP 4.1 волна 5 (T-4617; spec §5 E.2, §21): рестарт не начинает
        # Summary заново — незавершённый durable run чата ДОКАТЫВАЕТСЯ (тот
        # же стабильный run_id; окно — из durable snapshot'а, не перечитка).
        # Пермит-пул гарантирует один run на чат в живом процессе → активный
        # run-строка = прерванный рестартом. Fail-open; kill-switch OFF →
        # свежий run как сегодня (байт-в-бит 2.58.46).
        resumed = False
        try:
            from services import summary_run_store as srs
            _db = self._run_db()
            prior = None
            if srs.run_durable_enabled() and _db is not None:
                prior = await _db.get_active_summary_run_for_chat(chat_id)
            if prior is not None and str(prior.get("run_id") or ""):
                correlation_id = str(prior["run_id"])
                resumed = True
                logger.info(
                    "SUMMARY_RESUME | run_id=%s | chat_id=%s | state=%s — "
                    "продолжение незавершённого run (не пересоздание)",
                    correlation_id, chat_id, prior.get("state"))
        except Exception:      # pragma: no cover - fail-open
            resumed = False
        # S7 (ADR-1026-9 D2): режим (off|hybrid_l2) резолвим ОДИН раз и кладём
        # в SUMMARY_* (повторный вызов `_hybrid_l2_enabled` ниже не нужен).
        hybrid = await self._hybrid_l2_enabled(chat_id)
        ctx = RunContext(
            run_id=correlation_id, chat_id=chat_id,
            mode="hybrid_l2" if hybrid else "off", manual=manual,
            has_trigger=trigger_message_id is not None)
        # S7 (B-R1026S7-1, §109/D6): R17-safe модель/провайдер для
        # SUMMARY_FAILED на ОБОИХ путях — OFF (default) тоже error-поверхность;
        # `provider` — host без схемы/ключа; ON-ветка дублирует идемпотентно.
        # Best-effort: частично инициализированный инстанс (object.__new__ в
        # legacy-тестах) не должен падать из-за телеметрии.
        llm = getattr(self, "llm", None)
        ctx.model = str(getattr(llm, "_chat_model", "") or "") or None
        ctx.provider = provider_host(
            str(getattr(llm, "_base_url", "") or "")) or None
        # S7: жизненный цикл — SUMMARY_START; завершение (COMPLETE/FAILED)
        # эмитится в `finally` (в т.ч. на early-return и на исключении).
        try:
            log_summary_start(ctx)
        except Exception:  # pragma: no cover - лог best-effort, пайплайн не рвём
            pass
        # ASAP-4 волна E (T-4440, spec §5 E.1): SUMMARY_RUN_START в mca_events
        # (единый transport mca-17a; fail-open; kill-switch
        # SUMMARY_PIPELINE_EVENTS_ENABLED — OFF → no-op, бит-в-бит).
        try:
            from services import pipeline_events
            pipeline_events.summary_start(
                correlation_id, chat_id=chat_id, mode=ctx.mode, manual=manual)
        except Exception:  # pragma: no cover - эмиссия не рвёт пайплайн
            pass
        # ── ASAP 4.1 волна 5 (T-4616; spec §5 E.1): durable run-row (CREATED)
        # сразу после SUMMARY_START — стабильный summary_run_id (L-EXTRA-7).
        # Fail-open; kill-switch OFF → no-op (байт-в-бит 2.58.46).
        try:
            await self._durable_run_create(ctx)
        except Exception:  # pragma: no cover - fail-open
            pass
        try:
            await self.memory.compress_and_purge(chat_id)
            rows = None
            if resumed:
                # T-4617 (§21/spec A.1): окно докатываемого run'а — ТОЛЬКО
                # durable snapshot (перечитка истории запрещена — окно
                # дрейфует: `compress_and_purge` выполняется до чтения);
                # snapshot недоступен → fail-open к свежей перечитке
                # (честно: resumed-докат отменяется, не молча).
                try:
                    from services.summary_legacy_fullwindow import \
                        load_legacy_rows
                    rows = await load_legacy_rows(self._run_db(),
                                                  correlation_id)
                except Exception:      # pragma: no cover - fail-open
                    rows = None
                if rows:
                    logger.info(
                        "SOURCE_WINDOW_RESUMED | run_id=%s | chat_id=%s | "
                        "messages=%d (durable snapshot)", correlation_id,
                        chat_id, len(rows))
                else:
                    resumed = False
            if rows is None:
                rows = await self.memory.get_window_messages(chat_id)
            ctx.source_count = len(rows)
            # ASAP-2.1 (T-3986, раздел 4 spec): SOURCE_WINDOW — первое событие
            # после SUMMARY_START (замещает FILTER_*; R17 — только числа).
            logger.info(
                "SOURCE_WINDOW | run_id=%s | chat_id=%s | messages=%d",
                correlation_id, chat_id, len(rows))
            # Волна E: structured SOURCE_WINDOW (те же данные, что в логе —
            # §61.12: один structured source, без парсинга human-логов).
            try:
                from services import pipeline_events
                pipeline_events.source_window(
                    correlation_id, chat_id=chat_id, messages=len(rows))
            except Exception:  # pragma: no cover
                pass
            if not rows:
                if manual:
                    await self._send_ux(chat_id, _UX_EMPTY)     # B4
                logger.info(
                    "summary: empty window | chat_id=%s manual=%s — no LLM call",
                    chat_id, manual,
                )
                ctx.status = STATUS_EMPTY
                return
            # ── ASAP 4.1 волна 2 (T-4603, spec §1 A.1; ADR-1028-8 D1):
            # ЕДИНСТВЕННАЯ точка создания SummarySourceWindow — сразу после
            # SOURCE_WINDOW, до любой LLM-стадии (гибридный И legacy пути
            # получают один и тот же immutable snapshot по run_id/source_ref).
            # Окно = ВСЕ сообщения rows (никаких messages[:N]/last N — §1 ТЗ).
            # OFF-kill-switch → snapshot не пишется, контур байт-в-бит
            # 2.58.46. Fail-open: ошибка snapshot'а пайплайн не рвёт.
            try:
                await self._establish_source_window(
                    correlation_id, chat_id, rows, resumed=resumed)
            except Exception:  # pragma: no cover - fail-open
                logger.warning(
                    "summary: source window snapshot skipped | run_id=%s",
                    correlation_id, exc_info=True)
            # ASAP-2.1 (ADR-1028-1 D1, §2:2866): heuristic prefilter S1/S2
            # УДАЛЁН из live-пути полностью (не «выключен»): Hybrid И Legacy
            # получают ИСХОДНОЕ окно `rows`; отдельной сущности `xml_rows`
            # больше не существует. Физическое переполнение контекста
            # обрабатывает technical packing внутри run_l1/pack_l1_input
            # (eviction без весового члена, последнее сообщение неприкосновенно).
            if hybrid:
                # S6 (S-R1026S5-7, ADR-1026-11 D7): единый контур памяти —
                # `memorize_facts` вызывается и на ON (те же исходные `rows`,
                # тот же флаг, тот же fire-and-forget; второй контур не
                # создаётся). OFF-ветка ниже не меняется.
                if hot.get("flags.graph_rag_enabled", settings.GRAPH_RAG_ENABLED):
                    fire_and_forget(
                        self.memory.memorize_facts(
                            chat_id, _build_batch_text(rows, skip_empty=True),
                            "chat_history"),
                         "summary")
                await self._run_hybrid_l2(
                    chat_id, rows, focus, correlation_id, ctx=ctx,
                    trigger_message_id=trigger_message_id)
                return
            # ── ASAP-2 (контракт (i)/T-3950): тело OFF-ветки извлечено в
            # общий `_run_legacy_pipeline` (тот же метод для OFF-режима и
            # LEVEL-3 emergency fallback). OFF-поведение байт-в-байт. ────────
            await self._run_legacy_pipeline(
                chat_id, rows, focus, trigger_message_id,
                correlation_id, ctx)
        except LLMError as exc:
            ctx.fail_from_exc(stage="run", exc=exc,
                              code=CODE_SUMMARY_GENERATION_FAILED)
            logger.warning("summary: LLM failed | chat_id=%s | error=%s", chat_id, exc)
            await self._send_ux(chat_id, _UX_LLM_FAILED)
        except _SQLITE_ERRORS:
            ctx.fail(stage="db", reason="db_error", error_type="DatabaseError")
            logger.exception("summary: DB failed | chat_id=%s", chat_id)
            await self._send_ux(chat_id, _UX_DB_FAILED)
        except Exception as exc:
            ctx.fail_from_exc(stage="run", exc=exc,
                              code=CODE_SUMMARY_GENERATION_FAILED)
            logger.exception("summary: unexpected failure | chat_id=%s", chat_id)
            await self._send_ux(chat_id, _UX_GENERIC_FAILED)
        finally:
            # S7 (ADR-1026-9 D2/D6): SUMMARY_COMPLETE (ok/empty/degraded) либо
            # SUMMARY_FAILED; best-effort — ошибка логирования пайплайн не рвёт.
            try:
                finish_run(ctx)
            except Exception:  # pragma: no cover - лог не должен ронять прогон
                pass
            # S8 (ADR-1026-10 D2/D7): фиксация in-memory снапшота прогона для
            # карты вызовов (`/api/analytics/execution/latest`): узел `format`
            # + §112. С удалением S1 (ASAP-2.1) узел `algorithm` исчезает из
            # карты вызовов (замещается событиями §36: SOURCE_WINDOW /
            # L1_CONTEXT_PACK). Без DDL/persistence; best-effort — ошибка
            # снапшота пайплайн не рвёт и поведение не меняет.
            try:
                from services import execution_graph_source as _exec_graph
                _exec_graph.record_run_from_context(ctx, None)
            except Exception:  # pragma: no cover - снапшот не должен ронять прогон
                pass
            # Волна E (T-4440): SUMMARY_RUN_DONE — терминальное стадийное
            # событие (§61.11-срез coverage/publication/health; R17-safe).
            try:
                from services import pipeline_events
                pipeline_events.summary_done_from_ctx(ctx)
            except Exception:  # pragma: no cover - эмиссия не рвёт пайплайн
                pass
            # ── ASAP 4.1 волна 5 (T-4616): терминальный checkpoint
            # (DONE/DEGRADED/FAILED) + TTL-purge гейт (только терминальные).
            try:
                await self._durable_run_finish(ctx)
            except Exception:  # pragma: no cover - fail-open
                pass

    async def _establish_source_window(self, correlation_id: str, chat_id: int,
                                       rows: list, *, resumed: bool = False
                                       ) -> None:
        """Т-4603 (spec §1 A.1, ADR-1028-8 D1): единственная точка создания
        SummarySourceWindow run'а + fail-open выслеж retention TTL.

        Durable per-run row ``summary_source_windows`` (v24, additive);
        write-once: повторная запись не overwrite'ит (guard-инвариант
        immutability). Событие ``SUMMARY_SOURCE_WINDOW_READY`` — только
        числа/UTC-метки окна (R17). Событие эмиссится и при OFF
        kill-switch'а (snapshot не пишется — числа честно показывают
        in-memory-строку run'а; контур остаётся бит-в-бит 2.58.46).
        ``resumed`` (T-4617): окно докатываемого run'а уже в БД — запись
        пропускается (write-once и так её отклонил бы)."""
        from services import pipeline_events
        from services import summary_source_window as ssw

        db = getattr(self.memory, "db", None) if self.memory is not None \
            else None
        window_obj = ssw.build_source_window(correlation_id, chat_id, rows)
        stored = False
        if window_obj is not None and db is not None \
                and ssw.durable_enabled() and not resumed:
            stored = await ssw.store_source_window(db, window_obj)
            # Retention TTL (env-only, default 7 дней) — fail-open; удаляются
            # только окна старше горизонта (живые run'ы не задеваются).
            await ssw.purge_expired_source_windows(db)
        counts = window_obj.counts() if window_obj is not None \
            else {"messages": len(rows or ())}
        counts["durable"] = bool(stored)
        pipeline_events.source_window_ready(
            correlation_id, chat_id=chat_id, counts=counts,
            window_from=getattr(window_obj, "window_from", None),
            window_to=getattr(window_obj, "window_to", None))
        logger.info(
            "SUMMARY_SOURCE_WINDOW | run_id=%s | chat_id=%s | messages=%d | "
            "durable=%s", correlation_id, chat_id, counts["messages"], stored)
        # T-4616 (spec §5 E.1): checkpoint run-state → SOURCE_READY +
        # window_from/to/source_ref (стабильная связь с snapshot'ом). В
        # событии — R17-числа окна. Fail-open (snapshot-ошибка не рвёт run).
        try:
            from services import summary_run_store as srs
            if window_obj is not None:
                await srs.set_state(
                    self._run_db(), correlation_id, srs.STATE_SOURCE_READY,
                    window_from=window_obj.window_from,
                    window_to=window_obj.window_to,
                    source_ref=window_obj.source_ref)
        except Exception:      # pragma: no cover - fail-open
            pass

    # ── ASAP 4.1 волна 5 (T-4616/T-4617; spec §5 E.1/E.2; ADR-1028-8 D6) —
    # durable SummaryRun + идемпотентность публикации. Fail-open: любая
    # ошибка durable-слоя пайплайн не рвёт; kill-switch OFF → no-op
    # (байт-в-бит 2.58.46). Интеграция с RunContext — не дубль (R6-C-001):
    # ctx — in-memory витрина; summary_runs — durable checkpoint.

    def _run_db(self):
        """DatabaseService из memory (тот же db, что setup_summary)."""
        try:
            return getattr(self.memory, "db", None) if self.memory is not None \
                else None
        except Exception:      # pragma: no cover - защитная ветка
            return None

    async def _durable_run_create(self, ctx) -> None:
        """Создать durable run-row (CREATED) сразу после SUMMARY_START.
        Стабильный run_id (L-EXTRA-7): создаётся один раз, персистится."""
        try:
            from services import summary_run_store as srs
            await srs.create_run(self._run_db(), ctx.run_id, ctx.chat_id,
                                 manual=bool(ctx.manual))
        except Exception:      # pragma: no cover - fail-open
            logger.debug("[summary41] run create skipped", exc_info=True)

    async def _durable_mark(self, ctx, state: str, *, stage: str | None = None,
                            reason: str | None = None) -> None:
        """Checkpoint run-state (§20) + append-only stage event (§50.54)."""
        if ctx is None:
            return
        try:
            from services import summary_run_store as srs
            db = self._run_db()
            await srs.set_state(db, ctx.run_id, state)
            if stage:
                await srs.record_stage(
                    db, ctx.run_id, stage, status="ok", started_at=None,
                    provider=ctx.provider, model=ctx.model,
                    reason_code=reason)
        except Exception:      # pragma: no cover - fail-open
            pass

    async def _durable_stage_result(self, ctx, stage: str, status: str, *,
                                    reason: str | None = None) -> None:
        """Append-only stage event завершённой стадии (§50.54)."""
        if ctx is None:
            return
        try:
            from services import summary_run_store as srs
            await srs.record_stage(
                self._run_db(), ctx.run_id, stage, status=status,
                provider=ctx.provider, model=ctx.model, reason_code=reason)
        except Exception:      # pragma: no cover - fail-open
            pass

    async def _durable_run_finish(self, ctx) -> None:
        """Терминальный checkpoint (DONE/DEGRADED/FAILED по §20/§61.13) +
        TTL-purge гейт (только терминальные run'ы)."""
        if ctx is None:
            return
        try:
            from services import summary_run_store as srs
            db = self._run_db()
            published = (getattr(ctx, "publish_status", None) == "ok")
            state = srs.terminal_state_for_run(
                status=ctx.status, health=ctx.pipeline_health,
                published=published)
            await srs.set_state(db, ctx.run_id, state,
                                pipeline_health=ctx.pipeline_health or "ok")
            await srs.record_stage(
                db, ctx.run_id, "run", status=("ok" if published else
                                               str(ctx.status or "ok")),
                provider=ctx.provider, model=ctx.model,
                reason_code=ctx.reason)
            if state == srs.STATE_FAILED:
                await srs.fail_publication(db, ctx.run_id)
            await srs.purge_expired_runs(db)
        except Exception:      # pragma: no cover - fail-open
            pass

    async def _publication_gate(self, chat_id: int, run_id: str | None,
                                document) -> str | None:
        """T-4617 (ADR-1028-8 D6.2): идемпотентность публикации — PUBLISHING
        фиксируется в `summary_runs` ДО отправки; перед отправкой проверка
        publication_status (published → отправлять НЕЛЬЗЯ); kill-recovery
        (status=publishing, исход прошлой попытки неизвестен) — reconcile
        durable ledger'ом `bot_output_ledger` ПО correlation_id run'а
        (лестница R4-D-051: sent unknown → reconcile → retry). Возвращает
        ``"skip"`` — публикацию пропустить (двойной финал невозможен),
        иначе ``None``. Kill-switch OFF / нет run-row → None (байт-в-бит
        2.58.46)."""
        if not run_id:
            return None
        try:
            from services import summary_run_store as srs
        except Exception:      # pragma: no cover - fail-open
            return None
        if not srs.run_durable_enabled():
            return None
        db = self._run_db()
        if db is None:
            return None
        proceed, status = await srs.mark_publishing(db, run_id)
        if proceed:
            return None
        if status == srs.PUBLICATION_PUBLISHED:
            logger.info(
                "[summary41] publish skipped — already published "
                "| run_id=%s | chat_id=%s", run_id, chat_id)
            return "skip"
        # status == publishing: исход прошлой попытки неизвестен (kill в
        # PUBLISHING) → reconcile ФАКТОМ durable ledger'а этого же run'а
        # (correlation_id = стабильный summary_run_id — R4-D-051).
        record = None
        try:
            from services import bot_output_ledger as _bol
            if _bol.ledger_enabled():
                record = await db.get_bot_output_by_correlation(
                    chat_id, run_id)
        except Exception:      # pragma: no cover - fail-open
            record = None
        if record is None:
            # T-4617 content-hash барьер (REUSE bot_output_ledger): прошлый
            # заход мог доставить ТОТ ЖЕ контент (другой correlation —
            # ревизия/канал/ledger без correlation) — идентичный финальный
            # месседж не дублируется. Только ТОЧНОЕ совпадение hash'а
            # стабильного plain-рендера документа (fuzzy не считается —
            # C3); gate OFF / пустой текст → лег не активируется.
            try:
                from services import bot_output_ledger as _bol
                if _bol.ledger_enabled():
                    text = self._document_plain_text(document)
                    if text:
                        record = await _bol.find_bot_output_by_text(
                            db, chat_id, text)
            except Exception:      # pragma: no cover - fail-open
                record = None
        if record is not None:
            # Публикация этого run'а УЖЕ доставлена прошлой попыткой —
            # дублировать нельзя; run закрывается фактом доставки.
            await srs.complete_publication(
                db, run_id,
                result_ref=_bol.bot_output_source_ref_id(
                    record.get("output_id") or 0))
            logger.info(
                "[summary41] publish reconciled by ledger — skip "
                "| run_id=%s | chat_id=%s | output_id=%s", run_id, chat_id,
                record.get("output_id"))
            return "skip"
        return None    # reconcile не нашёл доставку → retry-лег: отправлять

    # ── ASAP 4.1 волна 3 (T-4609/T-4610; spec §2 B.3/B.4) — Writer/Reviewer
    # от Full SourceWindow (capacity-aware). ─────────────────────────────────

    def _source_window_rows(self, rows: list) -> list:
        """Сериализуемые строки окна для Writer-входа (§92-совместимый набор
        полей; никакого среза — окна полные, §1 ТЗ)."""
        return list(rows or [])

    async def _writer_capacity_fits(self, chat_id: int,
                                    content_tokens: int) -> tuple[bool, int]:
        """(fits, effective_window) Writer-входа по ФАКТИЧЕСКОМУ serialized
        payload (T-4609; spec §2 B.3, формула A.2: required+reserve ≤
        effective). Fail-open → (False, 0) — иерархический Writer (не
        oversized вслепую)."""
        try:
            from services import model_capacity as mc
            from services.summary_l2_writer import (
                _effective_base_url as _w_base,
                _effective_model as _w_model,
                resolve_l2_slot_safe,
            )
            from services.summary_hybrid_budget import (
                hybrid_output_reserve_tokens,
            )
            from services.summary_prompts import (
                PREV_SUMMARY_L2_WRITER_R1029_ASAP41,
                SUMMARY_L2_WRITER_SYSTEM_PROMPT,
            )
            slot = resolve_l2_slot_safe()
            model = _w_model(self.llm, slot) if self.llm is not None \
                else slot.model
            base_url = _w_base(self.llm, slot) if self.llm is not None \
                else slot.base_url
            default_prompt = (SUMMARY_L2_WRITER_SYSTEM_PROMPT
                              if _writer_source_input_enabled()
                              else PREV_SUMMARY_L2_WRITER_R1029_ASAP41)
            system = resolve_prompt(
                "prompts.summary_l2_writer_system_prompt", default_prompt)
            reserve = hybrid_output_reserve_tokens(kind="l2",
                                                   settings_obj=settings)
            cap = await mc.resolve_capacity(base_url, model,
                                            slot="summary.l2")
            plan = mc.decide_summary_mode(
                provider=cap.provider, model=model,
                effective_context_window=cap.effective_context_window,
                required_input_tokens=int(content_tokens)
                + count_tokens(system),
                reserved_output_tokens=reserve, window_source=cap.source,
                confidence=cap.confidence, fallback_used=cap.fallback_used)
            return plan.mode == mc.MODE_WHOLE_WINDOW, \
                plan.effective_context_window
        except Exception:      # pragma: no cover - fail-open (не бросает)
            logger.warning(
                "summary: writer capacity resolve failed — hierarchical "
                "Writer | chat_id=%s", chat_id, exc_info=True)
            return False, 0

    async def _reviewer_capacity_fits(self, chat_id: int,
                                      content_tokens: int,
                                      draft_tokens: int) -> bool:
        """Reviewer: полный window если влезает (T-4610, spec §2 B.4);
        иначе evidence-slices. Fail-open → False (slices — честный
        минимум)."""
        try:
            from services import model_capacity as mc
            from services.summary_l2_review import resolve_l2_reviewer_slot
            from services.summary_hybrid_budget import (
                hybrid_output_reserve_tokens,
            )
            reviewer = resolve_l2_reviewer_slot()
            model = reviewer.model if reviewer else ""
            base_url = reviewer.base_url if reviewer else ""
            cap = await mc.resolve_capacity(base_url, model,
                                            slot="summary.l2_reviewer")
            reserve = hybrid_output_reserve_tokens(kind="l2",
                                                   settings_obj=settings)
            plan = mc.decide_summary_mode(
                provider=cap.provider, model=model,
                effective_context_window=cap.effective_context_window,
                required_input_tokens=int(content_tokens)
                + int(draft_tokens) + reserve,
                reserved_output_tokens=reserve, window_source=cap.source,
                confidence=cap.confidence, fallback_used=cap.fallback_used)
            return plan.mode == mc.MODE_WHOLE_WINDOW
        except Exception:      # pragma: no cover - fail-open
            return False

    async def _merge_writer_documents(self, chat_id: int, documents: list,
                                      package: dict, service: dict,
                                      length: dict, correlation_id: str
                                      ) -> tuple[dict | None, object | None]:
        """Merge-pass иерархического Writer (T-4609): сегментные §99-документы
        → одна статья. Один LLM-вызов с бюджетом; невалидный merge →
        детерминированная склейка абзацев (НИЧЕГО не выбрасывается, no tail
        loss); и это тоже проходит валидацию.         Возвращает
        ``(document|None, l2_result|None)``."""
        from services.summary_l2_writer import (
            build_writer_merge_input,
            run_l2,
            validate_l2_document,
        )
        merge_content = build_writer_merge_input(documents, length=length)
        result = await run_l2(
            self.llm, package, service=service,
            correlation_id=correlation_id, chat_id=chat_id,
            source_input=merge_content, length=length)
        if result.usable:
            return result.document, result
        # Детерминированный merge (merge-LLM не дал валидный §99): склейка
        # абзацев сегментов в порядке сегментов (дедуп по evidence — нет:
        # сегменты не пересекаются по контенту, overlap только в source).
        title = ""
        paragraphs = []
        for doc in documents:
            if not isinstance(doc, dict):
                continue
            if not title:
                title = str(doc.get("title") or "")
            paragraphs.extend(doc.get("paragraphs") or [])
        merged = {"schema_version": 1, "title": title,
                  "paragraphs": paragraphs}
        document, _metrics = validate_l2_document(merged, package)
        if document is None:
            return None, result
        return document, None

    async def _run_writer_source_stage(self, chat_id: int, rows: list,
                                       payload_items: list, map_payload,
                                       package_result, service: dict,
                                       correlation_id: str, ctx=None, *,
                                       map_unavailable: bool = False,
                                       review_skipped_reason=None):
        """T-4609/T-4610 (spec §2 B.3/B.4; ADR-1028-8 D4/AM-4): Writer от
        Full SourceWindow; FactPackage = derived view (только валидация/
        roster); WHOLE_WINDOW — один вызов; CAPACITY_OVERFLOW — иерархический
        Writer (per-segment source+map → сегментные черновики → merge-pass,
        покрытие по построению: сегменты lossless). Reviewer — полный window
        если влезает, иначе evidence-slices; bounded revision ×2/budget ≤6 —
        без изменений. Никогда не бросает LLMError наружу (возвращает
        L2Result)."""
        from services.summary_fact_view import (
            ensure_full_id_space,
            fallback_view_for_items,
            slice_map_for_ids,
            slice_package_threads,
        )
        from services.summary_l1_clusterizer import (
            _partition_lossless,
            build_l1_payload,
        )
        from services.summary_l2_writer import (
            build_l2_source_input,
            run_l2,
            _hybrid_length_for_chat as _l2_length_for_chat,
        )
        from services.summary_hybrid_budget import (
            hybrid_output_reserve_tokens,
        )
        length = await _l2_length_for_chat(chat_id)
        review_on = _l2_review_enabled_safe()
        package = package_result.package if package_result is not None \
            else None
        source_content = build_l2_source_input(
            payload_items, semantic_map=map_payload, package=None,
            length=None, map_unavailable=map_unavailable)
        fits, effective = await self._writer_capacity_fits(
            chat_id, count_tokens(source_content))
        if fits:
            # WHOLE_WINDOW Writer: один вызов с полным окном (никаких
            # messages[:N]).
            source_input = build_l2_source_input(
                payload_items, semantic_map=map_payload, package=None,
                length=length, map_unavailable=map_unavailable)
            if review_on:
                # Reviewer: полный window если влезает; иначе evidence-slices
                # (T-4610, spec §2 B.4) — slices строятся от evidence
                # черновика ВНУТРИ run_l2_with_review (детерминированно из
                # SourceWindow).
                draft_tokens = int(length.get("target_chars") or 0) or 2000
                from services.summary_l2_review import run_l2_with_review
                if await self._reviewer_capacity_fits(
                        chat_id, count_tokens(source_content),
                        draft_tokens):
                    return await run_l2_with_review(
                        self.llm, package, service=service,
                        correlation_id=correlation_id, chat_id=chat_id,
                        ctx=ctx, writer_source_input=source_input,
                        writer_length=length, semantic_map=map_payload,
                        source_window_content=source_content,
                        source_message_ids=_source_window_ids(payload_items))
                return await run_l2_with_review(
                    self.llm, package, service=service,
                    correlation_id=correlation_id, chat_id=chat_id,
                    ctx=ctx, writer_source_input=source_input,
                    writer_length=length, semantic_map=map_payload,
                    review_full_window=False,
                    review_payload_items=payload_items,
                    source_message_ids=_source_window_ids(payload_items))
            return await run_l2(
                self.llm, package, service=service,
                correlation_id=correlation_id, chat_id=chat_id,
                source_input=source_input, length=length)
        # ── CAPACITY_OVERFLOW: иерархический Writer (по ledger-сегментам). ──
        from services.summary_l2_writer import validate_l2_document
        reserve = hybrid_output_reserve_tokens(kind="l2", settings_obj=settings)
        allowance = max(1, int(effective or 0) - reserve) \
            if effective > reserve else 2000
        partitions, _overlap = _partition_lossless(rows, chat_id, allowance,
                                                   "tokens")
        if len(partitions) <= 1:
            # Fit-решение сказало «не влезает», физика — один сегмент:
            # oversized → честный writer-фейл на полном входе (не рвём окно).
            source_input = build_l2_source_input(
                payload_items, semantic_map=map_payload, package=None,
                length=length, map_unavailable=map_unavailable)
            return await run_l2(self.llm, package, service=service,
                                correlation_id=correlation_id,
                                chat_id=chat_id, source_input=source_input,
                                length=length)
        logger.info(
            "L2_WRITER_HIERARCHICAL | run_id=%s | chat_id=%s | segments=%d | "
            "allowance=%d", correlation_id or "none", chat_id,
            len(partitions), allowance)
        documents = []
        for seg_index, segment in enumerate(partitions, start=1):
            seg_items = build_l1_payload(segment, chat_id)
            seg_ids = {item.get("message_id") for item in seg_items
                       if isinstance(item.get("message_id"), int)}
            seg_map = slice_map_for_ids(map_payload, seg_ids) \
                if map_payload else None
            seg_package = slice_package_threads(package, seg_ids) \
                if package else None
            if not (seg_package or {}).get("threads") and \
                    not (seg_package or {}).get("unassigned_message_ids"):
                # Сегмент без тредов в derived view → FALLBACK-заготовка
                # сегмента (chronology/fragments; Writer от окна — пакет
                # только валидация id-space, никогда не гильотина).
                seg_package = fallback_view_for_items(seg_items)
            # id-space сегментного пакета обязан покрывать ВСЕ id сегмента
            # (никогда не invalid_evidence от урезания derived view).
            seg_package = ensure_full_id_space(seg_package, seg_ids)
            content = build_l2_source_input(
                seg_items, semantic_map=seg_map, package=None, length=length)
            result = await run_l2(
                self.llm, seg_package, service=service,
                correlation_id=correlation_id, chat_id=chat_id,
                source_input=content, length=length)
            if not result.usable:
                # Честный writer-фейл (сегмент) → вызывающий контур
                # (LEVEL-3) решает; окно не теряется.
                return result
            documents.append(result.document)
        if len(documents) == 1:
            merged_doc = documents[0]
            merged_metrics = {"writer_segments": 1,
                              "writer_merge_mode": "single"}
        else:
            merged_doc, merge_result = await self._merge_writer_documents(
                chat_id, documents, package, service, length,
                correlation_id)
            if merged_doc is None:
                # Merge не дал валидного документа ни через LLM, ни
                # детерминированно — честный writer-фейл (LEVEL-3 решит).
                if merge_result is not None:
                    return merge_result
                from services.summary_l2_writer import invalid_result
                return invalid_result("invalid_merged_document",
                                      duration_ms=0.0)
            merged_metrics = {"writer_segments": len(documents),
                              "writer_merge_mode": "llm" if merge_result
                              else "deterministic"}
        document, _metrics = validate_l2_document(merged_doc, package)
        if document is None:
            from services.summary_l2_writer import invalid_result
            return invalid_result("invalid_merged_document",
                                  duration_ms=0.0,
                                  metrics=dict(merged_metrics))
        if ctx is not None:
            # Paged-прецедент (ADR-1028-5 D8): semantic review на
            # multi-call-пути не применяется — видимо, не тихо.
            if review_on:
                ctx.pipeline_health = "degraded"
                logger.info(
                    "L2_REVIEW_SKIPPED | run_id=%s | chat_id=%s | "
                    "reason=writer_hierarchical | segments=%d",
                    correlation_id or "none", chat_id, len(partitions))
        from services.summary_l2_writer import _make_result as _l2_make
        return _l2_make("ok", document=document, usage=None,
                        metrics=dict(merged_metrics), duration_ms=0.0)

    async def _hybrid_l2_enabled(self, chat_id: int) -> bool:
        """S5 (ADR-1026-7 D3/D5), AMEND S10 (ADR-1026-12 D2): режим генерации.

        env-only ``SUMMARY_HYBRID_L2_ENABLED`` (**default True** с S10) +
        hot-first ``flags.summary_hybrid_l2_enabled`` + per-chat через
        ``_chat_limit``; цепочка резолва байт-в-байт. Отсутствие override →
        ON (основной гибридный путь ``L1 → пакет → L2``); явный ``false``
        (env/default/hot/per-chat) → **аварийное выключение** (kill-switch) →
        прежний ``_generate_two_call`` байт-в-байт. «Ручная активация» не
        требуется (§107): после деплоя пайплайн включён по умолчанию.
        """
        try:
            return bool(await _chat_limit(
                chat_id, "flags.summary_hybrid_l2_enabled",
                hot.get("flags.summary_hybrid_l2_enabled",
                        getattr(settings, "SUMMARY_HYBRID_L2_ENABLED", False))))
        except Exception:  # pragma: no cover - защитная ветка
            return False

    async def _legacy_fallback_enabled(self, chat_id: int) -> bool:
        """ASAP-2 гейт LEVEL-3 (контракт (i)/Q6): hot
        ``flags.summary_legacy_fallback_enabled`` → env ClassVar. OFF —
        осознанный аварийный режим: hybrid-провал терминален."""
        try:
            return bool(await _chat_limit(
                chat_id, "flags.summary_legacy_fallback_enabled",
                hot.get("flags.summary_legacy_fallback_enabled",
                        getattr(settings, "SUMMARY_LEGACY_FALLBACK_ENABLED",
                                True))))
        except Exception:  # pragma: no cover - защитная ветка
            return True

    async def _build_legacy_full_window_context(
            self, chat_id: int, rows: list, correlation_id: str, ctx=None, *,
            semantic_package: dict | None = None
            ) -> tuple[str | None, dict | None]:
        """Волна C (T-4424, spec §3 C.3, ADR-1028-7 D7.3): контент истории
        для БОЛЬШОГО окна — иерархически свёрнутый full-window пакет вместо
        молчаливо обрезанного плоского XML (§55/§56), + честный coverage
        (§57; <100% — видимый degraded, никогда не тихий).

        Приоритет: готовый semantic package от Hybrid (тот же, что получил
        L2 — reuse, без второй редукции); при его отсутствии —
        детерминированная редукция окна (``build_fallback_package``:
        chronology = ВСЕ сообщения, fragments с авторским контекстом,
        budget = Legacy static resolve ``summary_max_context_*``).
        Возвращает ``(user_context | None, coverage | None)``; ``None`` —
        пакет не построился (пустое окно), вызывающий остаётся на плоском
        пути. R17: в логах только числа/коды. MAX_SUMMARY_PARTS не читается
        (§58: это cap выходных частей, не input coverage)."""
        from services import summary_legacy_fullwindow as _lfw
        source_total = len(rows or [])
        package: dict | None = None
        mode = "semantic_package"
        if isinstance(semantic_package, dict) \
                and isinstance(semantic_package.get("threads"), list) \
                and semantic_package.get("threads"):
            package = semantic_package
        else:
            mode = "hierarchical_reduction"
            try:
                from services.summary_fact_package import (
                    build_fallback_package,
                )
                from services.summary_l1_clusterizer import build_l1_payload
                kind, limit = resolve_chat_limit(
                    await _chat_limit(
                        chat_id, "limits.summary_max_context_tokens",
                        hot.get("limits.summary_max_context_tokens",
                                settings.SUMMARY_MAX_CONTEXT_TOKENS)),
                    _SUMMARY_CONTEXT_TOKEN_DEFAULT,
                    "SUMMARY_MAX_CONTEXT_CHARS",
                    await _chat_limit(
                        chat_id, "limits.summary_max_context_chars",
                        hot.get("limits.summary_max_context_chars",
                                settings.SUMMARY_MAX_CONTEXT_CHARS)),
                    "SUMMARY_MAX_CONTEXT",
                )
                budget_limit = safe_budget(limit) if kind == "tokens" \
                    else limit
                result = build_fallback_package(
                    build_l1_payload(rows, chat_id), budget=(kind,
                                                             budget_limit),
                    correlation_id=correlation_id, chat_id=chat_id,
                    reason="legacy_full_window")
                package = result.package if result is not None else None
            except Exception:      # pragma: no cover - защитная ветка
                logger.exception(
                    "legacy full window: package build failed | chat_id=%s",
                    chat_id)
                package = None
        if package is None:
            return None, None
        coverage = _lfw.compute_package_coverage(package, source_total)
        _lfw.log_full_window(
            run_id=correlation_id, chat_id=chat_id, mode=mode,
            source_total=coverage["source_messages_total"],
            considered=coverage["source_messages_considered"],
            coverage_percent=coverage["coverage_percent"])
        if ctx is not None:
            ctx.source_total = coverage["source_messages_total"]
            ctx.source_considered = coverage["source_messages_considered"]
            ctx.source_coverage = coverage["coverage_percent"]
        if coverage["coverage_percent"] < 100.0:
            # §57: fallback реально не покрыл весь source — degraded виден
            # (WARN + событие), НЕ молча.
            _lfw.log_coverage_degraded(
                run_id=correlation_id, chat_id=chat_id,
                source_total=coverage["source_messages_total"],
                considered=coverage["source_messages_considered"],
                coverage_percent=coverage["coverage_percent"],
                reason="legacy_coverage_partial")
            try:
                from services.agentic_events import (
                    SUMMARY_COVERAGE_DEGRADED,
                    emit_agentic_event,
                )
                emit_agentic_event(
                    SUMMARY_COVERAGE_DEGRADED,
                    source_messages=coverage["source_messages_total"],
                    processed_messages=coverage[
                        "source_messages_considered"],
                    unprocessed_messages=coverage["dropped"],
                    chunks=1,
                    coverage=coverage["coverage_percent"],
                    reason="legacy_coverage_partial")
            except Exception:      # fail-open
                pass
        return _lfw.build_legacy_package_content(package), coverage

    async def _run_legacy_pipeline(self, chat_id: int, rows: list,
                                   focus: str | None,
                                   trigger_message_id: int | None,
                                   correlation_id: str, ctx=None, *,
                                   max_parts: int | None = None,
                                   skip_memorize: bool = False,
                                   semantic_package: dict | None = None) -> bool:
        """ASAP-2 (контракт (i)/T-3950): ПОЛНЫЙ Legacy-пайплайн — общий метод
        OFF-режима (kill-switch Hybrid) и LEVEL-3 emergency fallback.

        Тело прежней OFF-ветки ``_run`` (XML+RAG+graph-подмешивание → System2
        two-call/single по ``SYSTEM2_SUMMARY_ENABLED`` → cover → rich/plain-
        доставка; plain-чанки ≤ ``limits.max_summary_parts`` — send-кап
        контракта (d)). LEVEL-3 вызывает с уже готовыми ``rows`` (окно НЕ
        перечитывается) и ``skip_memorize=True`` (fire-and-forget memorize уже
        сделан в hybrid-ветке ``_run`` — дубля памяти нет). ASAP-2.1 (D1):
        префильтра больше нет — ``rows`` здесь всегда исходное окно.

        ``max_parts=None`` → резолв hot→env (OFF-путь как раньше).
        Возвращает ``True``, если что-то опубликовано (для guard'а LEVEL-3);
        коды/UX/ctx — прежняя семантика §106. DoD-10: Legacy остаётся рабочим.

        Волна C (T-4424, spec §3 C.3, ADR-1028-7 D7.3): при
        ``SUMMARY_LEGACY_FULL_WINDOW_ENABLED`` (default ON) и большом окне —
        тихий XML hard stop удалён: Legacy получает иерархически свёрнутый
        full-window пакет (``semantic_package`` от Hybrid либо
        детерминированная редукция окна) + честный coverage (§57; <100% —
        видимый degraded). Малые окна и OFF — плоский ``<chat_history>``
        бит-в-бит. ``MAX_SUMMARY_PARTS`` не трогается (§58).

        Волна 3 (T-4611, spec §3; EXTEND ADR-1028-7 D7.3): при
        ``SUMMARY_LEGACY_SOURCE_WINDOW_ENABLED`` (default ON) — Legacy
        начинает с SummarySourceWindow (source_ref; тот же snapshot с
        Hybrid); фиксированные капы окна (50k chars/500 messages) больше НЕ
        триггер «стоп» — ветка capacity-aware: (а) Legacy-модель вмещает
        full-window → один запрос (плоский XML остаётся форматом); (б) не
        вмещает → CAPACITY_OVERFLOW hierarchical legacy (lossless сегменты;
        reduction ``summary_semantic_reduction`` REUSE; coverage 100%);
        (в) coverage <100% (сегмент упал) → честный degraded (событие +
        health), не молча. Output: split delivery без потери tail
        (``MAX_SUMMARY_PARTS`` — soft target промпта, не усечение выдачи,
        §33). OFF → контур 2.58.46 байт-в-бит.
        """
        # T-4616: durable run store (обёртки fail-open; OFF → no-op).
        from services import summary_run_store as _srs
        if max_parts is None:
            max_parts = int(hot.get("limits.max_summary_parts",
                                    settings.MAX_SUMMARY_PARTS))
        zone_c = _legacy_source_window_enabled()
        if zone_c:
            # T-4611: Legacy начинает с SummarySourceWindow (source_ref) —
            # единый snapshot с Hybrid; fail-open к переданным rows.
            from services import summary_legacy_fullwindow as _lfw_zone
            _db = getattr(self.memory, "db", None) \
                if self.memory is not None else None
            if _db is not None and correlation_id:
                snap_rows = await _lfw_zone.load_legacy_rows(
                    _db, correlation_id)
                if snap_rows:
                    rows = snap_rows
        xml_context = self.xml.build(
            rows, self.aliases, trigger_message_id,
            window_caps=(None, None) if zone_c else None)
        # ── Волна C (T-4424): full-window режим определяется ПОСЛЕ сборки
        # плоского XML — «влез ли он целиком» знает только билдер. OFF или
        # малое окно → xml_context как раньше (бит-в-бит); большое окно при
        # ON → контент пакета заменяет только секцию истории чата.
        full_window_context: str | None = None
        full_window_coverage: dict | None = None
        if getattr(settings, "SUMMARY_LEGACY_FULL_WINDOW_ENABLED", True):
            from services import summary_legacy_fullwindow as _lfw
            if not _lfw.flat_fits(xml_context, len(rows)):
                (full_window_context, full_window_coverage) = (
                    await self._build_legacy_full_window_context(
                        chat_id, rows, correlation_id, ctx,
                        semantic_package=semantic_package))
        keywords = self._extract_keywords(rows)
        l2_rows = await self.memory.search_long_term(
            chat_id, keywords, await _chat_limit(
                chat_id, "limits.summary_rag_l2_limit",
                hot.get("limits.summary_rag_l2_limit",
                        settings.SUMMARY_RAG_L2_LIMIT)))
        l2_quotes = [
            self._format_l2_quote(row)
            for row in l2_rows
            if row["text"]
        ]
        l3_facts = await self.memory.vector_search(
            chat_id, " ".join(keywords), hot.get("limits.summary_rag_l3_limit", settings.SUMMARY_RAG_L3_LIMIT)
        )
        try:
            graph_facts = await self.memory.get_graph_facts(chat_id, rows, keywords)
        except Exception:
            logger.warning(
                "summary: graph facts lookup failed — summary without graph section | chat_id=%s",
                chat_id, exc_info=True,
            )
            graph_facts = []
        if (not skip_memorize
                and hot.get("flags.graph_rag_enabled", settings.GRAPH_RAG_ENABLED)):
            fire_and_forget(
                self.memory.memorize_facts(
                    chat_id, _build_batch_text(rows, skip_empty=True), "chat_history"),
                "summary")
        # 10.20 (БЛОК 2.6, ADR-1020-2): ASC-хронология перед рендером.
        rag_context = await self.memory.get_rag_context(
            chat_id, " ".join(keywords), sort_by_timestamp=True)
        user_content = self._compose_user_content(
            full_window_context or xml_context, l2_quotes, l3_facts,
            graph_facts, rag_context=rag_context
        )
        # Epic 65: фокус «/summary про X» — блок в НАЧАЛО user_content
        # (SIGIR'26: важное — к краям промпта). System-канон R11 НЕ тронут.
        user_content = _apply_focus(user_content, focus)
        # Epic 60 (64.7, T-468): потолок-проверка user_content перед
        # generate — токены (SUMMARY_MAX_CONTEXT_TOKENS, срез С КОНЦА;
        # chars — fallback). Таймер 6ч/крон НЕ меняются.
        # ASAP-2 §11/D7: Legacy-контур читает ТОЛЬКО limits.summary_max_context_*.
        kind, limit = resolve_chat_limit(
            await _chat_limit(chat_id, "limits.summary_max_context_tokens",
                hot.get("limits.summary_max_context_tokens",
                        settings.SUMMARY_MAX_CONTEXT_TOKENS)),
            _SUMMARY_CONTEXT_TOKEN_DEFAULT,
            "SUMMARY_MAX_CONTEXT_CHARS",
            await _chat_limit(chat_id, "limits.summary_max_context_chars",
                hot.get("limits.summary_max_context_chars",
                        settings.SUMMARY_MAX_CONTEXT_CHARS)),
            "SUMMARY_MAX_CONTEXT",
        )
        full_window_truncated = False
        zone_fits = True
        effective_window = 0
        if zone_c:
            # T-4611 (spec §3): фиксированные капы окна больше НЕ триггер
            # «стоп»; решение — эффективная capacity Legacy-модели по
            # фактическому serialized user_content (формула A.2).
            zone_fits, effective_window = await self._legacy_capacity_fits(
                chat_id, count_tokens(user_content), max_parts)
            if not zone_fits:
                # (б) CAPACITY_OVERFLOW → hierarchical legacy (lossless
                # сегменты; reduction REUSE; coverage честный, <100% —
                # видимый degraded).
                raw = await self._run_legacy_hierarchical(
                    chat_id, rows, focus, correlation_id, ctx, max_parts,
                    effective_window)
                if raw is None:
                    # Ни один сегмент не дал текста — публикации нет (§106/D5).
                    if ctx is not None:
                        ctx.status = STATUS_DEGRADED
                        ctx.code = CODE_SUMMARY_GENERATION_FAILED
                    return False
        elif kind == "tokens":
            budget = safe_budget(limit)
            if count_tokens(user_content) > budget:
                logger.warning(
                    "summary: user content truncated | tokens=%d -> %d",
                    count_tokens(user_content), budget)
                user_content = truncate_to_tokens(user_content, budget)
                full_window_truncated = full_window_context is not None
        elif len(user_content) > limit:
            logger.warning(
                "summary: user content truncated | chars=%d", len(user_content))
            user_content = user_content[-limit:]
            full_window_truncated = full_window_context is not None
        if not zone_c and full_window_truncated \
                and full_window_coverage is not None:
            # §57: даже safety-срез поверх пакета — видимая деградация
            # coverage, никогда не молча.
            from services import summary_legacy_fullwindow as _lfw
            _lfw.log_coverage_degraded(
                run_id=correlation_id, chat_id=chat_id,
                source_total=full_window_coverage["source_messages_total"],
                considered=full_window_coverage["source_messages_considered"],
                coverage_percent=full_window_coverage["coverage_percent"],
                reason="legacy_budget_reduction")
            if ctx is not None:
                ctx.source_coverage = min(
                    ctx.source_coverage or 100.0,
                    full_window_coverage["coverage_percent"])
        # ASAP-2 §1 (контракт (d)): prompt-бюджет legacy = parts×4000−200
        # (parts — hot `limits.max_summary_parts` → env; назад совместимо).
        max_symbols = max_parts * 4000 - 200
        # NOTE: {username} must stay literal in the prompt (R11), so we
        # substitute only {max_symbols} via replace, not str.format.
        # T-619: промпт саммари — горячая точка (фолбек код-канона).
        summary_prompt = hot.get("prompts.summary_system_prompt", SYSTEM_PROMPT)
        system = summary_prompt.replace("{max_symbols}", str(max_symbols))
        payload = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ]
        # Раунд 10.22 (F4, ADR-1022-4): System 2 — Редактор (Markdown-выжимка)
        # → Рассказчик (plain R11). Невалидный digest/провал → одиночный путь.
        draft: SummaryDraft | None = None
        if zone_c and not zone_fits:
            # T-4611: raw уже получен hierarchical legacy (join сегментов,
            # cleanup на месте); two_call/single поверх не нужен.
            pass
        elif getattr(settings, "SYSTEM2_SUMMARY_ENABLED", True):
            draft = await self._generate_two_call(
                user_content, max_symbols, chat_id, correlation_id)
            if draft is not None:
                raw = draft.text
            else:
                logger.info(
                    "summary system2: fallback на одиночный путь 10.21 | "
                    "chat_id=%s", chat_id)
                raw = await self._llm_generate(
                    payload, chat_id, correlation_id=correlation_id,
                    step="single")
        else:
            raw = await self._llm_generate(
                payload, chat_id, correlation_id=correlation_id,
                step="single")
        if raw is None:
            # §106/D5: LLM не дал ответа → публикации нет.
            if ctx is not None:
                ctx.status = STATUS_DEGRADED
                ctx.code = CODE_SUMMARY_GENERATION_FAILED
            return False
        raw = cleanup_llm_text(raw)                   # Epic 28 (R28-3)
        raw = _strip_safe_html(raw)                   # review iter1 (H2)
        if not raw.strip():
            # Epic 60 (65.1): после cleanup пусто → молчание (без реакции:
            # message_id в manual-ветку не передаётся — 65.1).
            logger.warning(
                "summary: empty answer after cleanup — silence | chat_id=%s",
                chat_id)
            if ctx is not None:
                ctx.status = STATUS_EMPTY
                # §106/D5: пустой текст после cleanup — класс генерации.
                ctx.code = CODE_SUMMARY_GENERATION_FAILED
            return False
        # ASAP-2.1 (контракт (e)/§25): код больше НЕ дописывает «главного
        # шиза» поверх текста модели — выбор за LLM (инструкция в каноне).
        text = raw
        # T-4616/T-4618: checkpoint TEXT_READY (approved text snapshot) —
        # общий для Legacy-пути (cover/publish ниже подписываются на него).
        try:
            await self._durable_mark(ctx, _srs.STATE_TEXT_READY)
        except Exception:      # pragma: no cover - fail-open
            pass
        # T-4624 (spec §7.3; §42 ТЗ): SUMMARY_TEXT_READY в mca_events
        # (единый transport; fail-open). Stage: legacy — до обложки.
        try:
            from services import pipeline_events as _pe
            _pe.text_ready(correlation_id, chat_id=chat_id, stage="legacy")
        except Exception:      # pragma: no cover - эмиссия не рвёт
            pass
        cover_prompt = self._resolve_cover_prompt(
            draft, text, chat_id)
        # S6 (ADR-1026-11 D2): заголовок digest Stage-1 → настоящий H1 в
        # rich-пути / жирный заголовок в plain; нет draft → fallback §5.3
        # в детерминированном адаптере (0 LLM).
        title = draft.title if draft is not None else ""
        # AMEND ADR-1026-7 D5 / ADR-1026-9 D7 (effective S6): «OFF
        # байт-в-байт» сужается до слоя генерации (промпты/2 вызова/XML/
        # память/RAG/обложка); формат доставки OFF намеренно меняется по
        # §100–§105 (§101/§102 rich, §105 plain).
        # F6 (ADR-1023-6 §3.4): Article-ветка — только если флаг ON,
        # обложка возможна и aiogram поддерживает media. Иначе — plain
        # (S6: §105-формат: `<b>title</b>` + абзацы).
        if (cover_prompt
                and getattr(settings, "SUMMARY_COVER_ARTICLE_ENABLED", True)
                and _rich_media_supported()):
            return await self._deliver_rich(
                chat_id, text, cover_prompt,
                correlation_id=correlation_id, ctx=ctx, title=title)
        if ctx is not None:
            ctx.cover_status = "unavailable"
        return await self._deliver_plain(
            chat_id, text, title=title,
            correlation_id=correlation_id, ctx=ctx,
            split_delivery=_legacy_split_delivery_enabled())

    async def _legacy_capacity_fits(self, chat_id: int, content_tokens: int,
                                    max_parts: int) -> tuple[bool, int]:
        """(fits, effective) Legacy-модели по ФАКТИЧЕСКОМУ serialized
        user_content (T-4611, spec §3 (а)/(б); формула A.2). Reserve —
        output-цель Legacy (parts × 4000−200 chars ≈ parts×1000 токенов,
        developer-bound; документировано, не SLA). Fail-open → (False, 0)
        (не влезает → hierarchical — safe reduction)."""
        try:
            from services import model_capacity as mc
            llm = getattr(self, "llm", None)
            model = str(getattr(llm, "_chat_model", "") or "") \
                if llm is not None else ""
            base_url = str(getattr(llm, "_base_url", "") or "") \
                if llm is not None else ""
            cap = await mc.resolve_capacity(base_url, model,
                                            slot="summary.legacy")
            reserve_tokens = max(1000, int(max_parts) * 1000)
            plan = mc.decide_summary_mode(
                provider=cap.provider, model=model,
                effective_context_window=cap.effective_context_window,
                required_input_tokens=int(content_tokens),
                reserved_output_tokens=reserve_tokens,
                window_source=cap.source, confidence=cap.confidence,
                fallback_used=cap.fallback_used)
            return plan.mode == mc.MODE_WHOLE_WINDOW, \
                plan.effective_context_window
        except Exception:      # pragma: no cover - fail-open (не бросает)
            return False, 0

    async def _run_legacy_hierarchical(self, chat_id: int, rows: list,
                                       focus: str | None,
                                       correlation_id: str, ctx=None,
                                       max_parts: int = 1,
                                       effective_window: int = 0) -> str | None:
        """CAPACITY_OVERFLOW hierarchical legacy (T-4611, spec §3 (б)/(в);
        EXTEND ADR-1028-7 D7.3): full window → lossless сегменты
        (``_partition_lossless``, serialized §92-учёт) → per-segment
        fallback-view + reduction ``summary_semantic_reduction`` REUSE
        (REUSE существующих механизмов; новый reducer не создаётся) →
        per-segment Legacy-вызов → join БЕЗ потери tail. Coverage честный:
        сегмент упал → ``LEGACY_COVERAGE_DEGRADED`` + ctx.health degraded
        (не молча, coverage <100%). Возвращает готовый текст (или None —
        ни одного сегмента)."""
        from services import summary_l1_clusterizer as _sl1
        from services import summary_legacy_fullwindow as _lfw
        from services.summary_fact_package import (
            build_fallback_package,
            semantic_reduction_enabled,
        )
        from services.summary_semantic_reduction import reduce_threads
        reserve_tokens = max(1000, int(max_parts) * 1000)
        allowance = max(1, int(effective_window or 0) - reserve_tokens) \
            if effective_window > reserve_tokens else 2000
        partitions, _overlap = _sl1._partition_lossless(rows, chat_id,
                                                        allowance, "tokens")
        logger.info(
            "LEGACY_HIERARCHICAL | run_id=%s | chat_id=%s | segments=%d | "
            "allowance=%d", correlation_id or "none", chat_id,
            len(partitions), allowance)
        texts: list[str] = []
        covered: set = set()
        source_total = len(rows)
        max_symbols = max_parts * 4000 - 200
        summary_prompt = hot.get("prompts.summary_system_prompt",
                                 SYSTEM_PROMPT)
        system = summary_prompt.replace("{max_symbols}", str(max_symbols))
        for seg_index, segment in enumerate(partitions, start=1):
            seg_items = _sl1.build_l1_payload(segment, chat_id)
            view = build_fallback_package(
                seg_items, budget=("tokens", allowance),
                correlation_id=correlation_id, chat_id=chat_id,
                reason="legacy_hierarchical_segment")
            if view is None or not view.deliverable:
                continue
            if semantic_reduction_enabled():
                threads, _stats = reduce_threads(view.package["threads"])
                view.package["threads"] = threads
            content = _lfw.build_legacy_package_content(view.package)
            payload = [
                {"role": "system", "content": system},
                {"role": "user", "content": _apply_focus(content, focus)},
            ]
            raw = await self._llm_generate(
                payload, chat_id, correlation_id=correlation_id,
                step="legacy_segment")
            if raw is None:
                # Сегмент упал → честный degraded coverage (не молча).
                _lfw.log_coverage_degraded(
                    run_id=correlation_id, chat_id=chat_id,
                    source_total=source_total,
                    considered=len(covered), coverage_percent=0.0
                    if not covered else round(100.0 * len(covered)
                                              / max(1, source_total), 2),
                    reason="legacy_hierarchical_segment_failed")
                if ctx is not None:
                    ctx.pipeline_health = "degraded"
                continue
            text = _strip_safe_html(cleanup_llm_text(raw)).strip()
            if not text:
                _lfw.log_coverage_degraded(
                    run_id=correlation_id, chat_id=chat_id,
                    source_total=source_total, considered=len(covered),
                    coverage_percent=round(100.0 * len(covered)
                                           / max(1, source_total), 2),
                    reason="legacy_hierarchical_segment_empty")
                if ctx is not None:
                    ctx.pipeline_health = "degraded"
                continue
            texts.append(text)
            covered.update(item.get("message_id") for item in seg_items
                           if isinstance(item.get("message_id"), int))
        if not texts:
            return None
        coverage = 100.0 if source_total == 0 else \
            min(100.0, round(100.0 * len(covered) / max(1, source_total), 2))
        if ctx is not None:
            ctx.source_total = source_total
            ctx.source_considered = len(covered)
            ctx.source_coverage = coverage
            if coverage < 100.0:
                ctx.pipeline_health = "degraded"
                logger.warning(
                    "LEGACY_COVERAGE_DEGRADED | run_id=%s | chat_id=%s | "
                    "coverage=%.2f%% — hierarchical partial (не молча)",
                    correlation_id or "none", chat_id, coverage)
        logger.info(
            "LEGACY_HIERARCHICAL_MERGED | run_id=%s | chat_id=%s | "
            "segments_used=%d/%d | coverage=%.2f%%",
            correlation_id or "none", chat_id, len(texts),
            len(partitions), coverage)
        return "\n\n".join(texts)

    async def _run_hybrid_l2(self, chat_id: int, rows: list,
                             focus: str | None,
                             correlation_id: str, ctx=None, *,
                             trigger_message_id: int | None = None) -> None:
        """S5 + ASAP-2 (ADR-1027-10 D3/D4/D8, контракты (i)): ON-ветка —
        двухконтурная fail-soft цепочка.

        ``rows`` — исходное окно (ASAP-2.1/ADR-1028-1 D1: префильтра больше
        нет; для LEVEL-2 fallback-пакета, LEVEL-3 Legacy-пересборки окно НЕ
        перечитывается — те же строки).

        LEVEL-1: run_l1 (repair + correction retry внутри).
        LEVEL-2: L1 непригоден (ЛЮБАЯ причина: invalid после retry, error/
        timeout, useless, too_many_*, empty) или FactPackage не deliverable при
        usable L1 (defense) → deterministic ``build_fallback_package`` → **L2
        вызывается в любом случае** (§8:2260); обложка деградированного пути —
        детерминированная ``_derive_fallback_cover_prompt`` (DoD-14).
        LEVEL-3: L2 unusable (обычный И fallback-пакет; L2-retry НЕ вводится),
        plain-доставка hybrid-текста провалилась, непредвиденное исключение при
        неопубликованном → полный ``_run_legacy_pipeline`` (гейт
        ``flags.summary_legacy_fallback_enabled``). Guard двойной публикации:
        входим ТОЛЬКО если ничего не отправлено (``published``).
        Worst case ≤5 генераций: 1 L1 + ≤1 correction (внутри run_l1) + ≤1 L2
        + ≤2 Legacy (ADR-1027-10 D3; AMEND ADR-1026-7 D5 отменён владельцем).
        Промежуточные коды НЕ порождают UX-сообщений, пока цепочка работает
        (§106/AMEND ADR-1026-11 D5); ``SUMMARY_GENERATION_FAILED`` — только
        когда и Legacy провалился (матрица строка 11).
        """
        # Ленивые импорты: OFF-путь не тянет модули L2 (байт-в-байт).
        from services.summary_fact_package import (
            build_fact_package,
            build_fallback_package,
        )
        from services.summary_l1_clusterizer import (
            build_l1_payload,
            run_l1,
        )
        from services.summary_l2_writer import run_l2
        # T-4616: durable run store (лёгкий модуль; обёртки fail-open,
        # kill-switch OFF → no-op — байт-в-бит 2.58.46).
        from services import summary_run_store as _srs
        # ASAP-3.1 (T-4069): L2-пакет — тот же Auto Budget Resolver
        # (capacity слота summary.l2; OFF → прежний static hybrid-путь).
        try:
            from services.summary_budget_auto import resolve_l2_package_budget
            l2_budget = await resolve_l2_package_budget()
        except Exception:
            l2_budget = None
        # S7: R17-safe модель/провайдер для SUMMARY_FAILED (host, без ключа).
        if ctx is not None:
            ctx.model = str(getattr(self.llm, "_chat_model", "") or "") or None
            ctx.provider = provider_host(
                str(getattr(self.llm, "_base_url", "") or "")) or None
        published = False
        calls_so_far = 0          # гибрид-вызовы LLM до точки отказа (R17)
        fallback_used = False
        package_result = None     # до первого присваивания в try (closure)

        async def _legacy_fallback(reason: str) -> bool:
            """LEVEL-3 (контракт (i), матрица строки 3–6/9–10): полный Legacy-
            пайплайн на уже готовых строках; guard — только если ничего не
            отправлено; гейт ``flags.summary_legacy_fallback_enabled``."""
            nonlocal calls_so_far
            if published:
                return False                      # guard двойной публикации
            if not await self._legacy_fallback_enabled(chat_id):
                logger.warning(
                    "LEGACY_FALLBACK | run_id=%s | chat_id=%s | reason=%s | "
                    "calls_so_far=%d — ВЫКЛЮЧЕН (flags.summary_legacy_fallback_"
                    "enabled=false): прогон терминален",
                    correlation_id or "none", chat_id, reason, calls_so_far)
                return False
            logger.warning(
                "LEGACY_FALLBACK | run_id=%s | chat_id=%s | reason=%s | "
                "calls_so_far=%d", correlation_id or "none", chat_id,
                reason, calls_so_far)
            try:
                # Волна C (T-4424, ADR D7.3): Legacy получает тот же
                # hierarchical-reduced пакет, что и L2 (reuse full-window
                # semantic package) — большой window не теряется молча.
                delivered = await self._run_legacy_pipeline(
                    chat_id, rows, focus, trigger_message_id, correlation_id,
                    ctx, skip_memorize=True,
                    semantic_package=(package_result.package
                                      if package_result is not None
                                      and getattr(package_result,
                                                  "deliverable", False)
                                      else None))
            except LLMError as exc:
                logger.warning("summary legacy fallback: LLM failed | "
                               "chat_id=%s | error=%s", chat_id, exc)
                delivered = False
                if ctx is not None:
                    ctx.fail_from_exc(stage="legacy", exc=exc,
                                      code=CODE_SUMMARY_GENERATION_FAILED)
            except Exception as exc:  # noqa: BLE001 - best-effort own try
                logger.exception("summary legacy fallback failed | chat_id=%s",
                                 chat_id)
                delivered = False
                if ctx is not None:
                    ctx.fail_from_exc(stage="legacy", exc=exc,
                                      code=CODE_SUMMARY_GENERATION_FAILED)
            if delivered:
                # §18: SUMMARY_COMPLETE fallback=legacy — только при реальной
                # legacy-доставке (не при неудачной попытке).
                if ctx is not None:
                    ctx.fallback = "legacy"
                    # Волна E (T-4440): SUMMARY_LEGACY_FALLBACK — fallback
                    # виден отдельно от failure (§61.7).
                    try:
                        from services import pipeline_events
                        pipeline_events.legacy_fallback(
                            correlation_id, chat_id=chat_id, trigger=reason,
                            from_stage=str(ctx.stage or "l2"))
                    except Exception:  # pragma: no cover
                        pass
                    # Промежуточные коды цепочки (degraded L2/exception на
                    # неопубликованном) НЕ терминальны, если Legacy довёл до
                    # публикации (матрица строки 3–10 vs 11): снимаем
                    # промежуточный статус/поверхность ошибки.
                    if ctx.status in (STATUS_DEGRADED, STATUS_FAILED):
                        ctx.status = STATUS_OK
                    # Волна D (T-4436, §50.53, прод-факт Q36): publication
                    # (status=OK) и health — РАЗДЕЛЬНЫЕ оси. «L2 rejected →
                    # Legacy used» больше не стирается успешной публикацией:
                    # health остаётся degraded (stage_events append-only).
                    if ctx.status == STATUS_OK and not getattr(
                            ctx, "pipeline_health", None):
                        ctx.pipeline_health = "degraded"
                    ctx.code = None
                    ctx.stage = None
                    ctx.reason = None
                    ctx.error_type = None
                    ctx.http_status = None
                return True
            if ctx is not None:
                # Матрица строка 11: Legacy тоже провалился — единственный
                # терминальный SUMMARY_GENERATION_FAILED этой ветки.
                ctx.status = STATUS_DEGRADED
                ctx.stage = "legacy"
                ctx.code = CODE_SUMMARY_GENERATION_FAILED
            return False

        stage = "l1"
        # T-4616: checkpoint STRUCTURING (L1 старт). Fail-open.
        try:
            await self._durable_mark(ctx, _srs.STATE_STRUCTURING)
        except Exception:  # pragma: no cover - fail-open
            pass
        try:
            l1_result = await run_l1(
                llm=self.llm, rows=rows, chat_id=chat_id,
                correlation_id=correlation_id,
                focus_block=_apply_focus("", focus))
            calls_so_far += 1
            if ctx is not None:
                ctx.threads = getattr(l1_result, "threads_count", None)
            # Волна E (T-4440): SUMMARY_L1_STAGE (ok / invalid+reason).
            # Волна 3 (T-4607/T-4608, R6-G-001): честный срез карты —
            # map_degraded/minimal-maps видны рядом с результатом
            # (Inspector не покажет «L1 ok» без деградации).
            try:
                from services import pipeline_events
                _map_degraded = int(bool(getattr(
                    l1_result, "map_degraded", False)))
                _map_counts = {"map_degraded": _map_degraded}
                if _map_degraded:
                    _map_counts["map_reason"] = str(
                        getattr(l1_result, "map_reason", None) or "")
                pipeline_events.l1_stage(
                    correlation_id, chat_id=chat_id,
                    usable=bool(l1_result.usable),
                    invalid_reason=getattr(l1_result, "invalid_reason", None),
                    duration_ms=getattr(l1_result, "duration_ms", None),
                    threads=getattr(l1_result, "threads_count", None),
                    counts=_map_counts)
            except Exception:  # pragma: no cover
                pass
            # T-4616: checkpoint STRUCTURE_READY (L1 результат получен) +
            # append-only stage event честного исхода L1 (§50.54).
            try:
                await self._durable_mark(ctx, _srs.STATE_STRUCTURE_READY)
                await self._durable_stage_result(
                    ctx, "l1", "ok" if l1_result.usable else "failed",
                    reason=str(getattr(l1_result, "invalid_reason", None)
                               or "") or None)
            except Exception:  # pragma: no cover - fail-open
                pass
            payload_items = build_l1_payload(rows, chat_id)
            writer_source = _writer_source_input_enabled()
            # T-4607: map-payload L1 (semantic map v1) — по форме выхода
            # (map-режим врезается только в capacity-first ветке run_l1).
            map_payload = None
            if writer_source and isinstance(getattr(l1_result, "payload",
                                                    None), dict) \
                    and "topics" in (l1_result.payload or {}):
                map_payload = l1_result.payload
            # §18/контракт (k): L2_SKIPPED l1_not_usable больше НЕ терминален
            # («не публикуем» снят) — переход в LEVEL-2 (L1_FALLBACK_PACKAGE).
            if not l1_result.usable:
                stage = "package"
                if writer_source:
                    # T-4608 (spec §2 B.2; ADR-1028-8 D3.4; §48 Run 1:
                    # 23700–23701): L1 failed ≠ Summary failed; переход на
                    # урезанный Legacy из-за L1 ЗАПРЕЩЁН. fallback-package —
                    # ОПЦИОНАЛЬНАЯ derived view (AM-5); Writer получает Full
                    # SourceWindow + instruction «semantic map unavailable —
                    # structure source yourself».
                    package_result = build_fallback_package(
                        payload_items, correlation_id=correlation_id,
                        chat_id=chat_id,
                        reason=str(getattr(l1_result, "invalid_reason", None)
                                   or getattr(l1_result, "status", None)
                                   or "l1_unusable"),
                        budget=l2_budget)
                    fallback_used = True
                    if package_result is None:
                        # Пустой payload (0 сообщений после фильтра) — НЕ
                        # failure: существующая empty-семантика (строка 2).
                        if ctx is not None:
                            ctx.status = STATUS_EMPTY
                            ctx.stage = "package"
                            ctx.reason = "l1_empty_payload"
                        return
                else:
                    # ASAP-3.1 incident fix 29.09.2026 (M-ASAP31-3): тот же
                    # resolver-бюджет, что и в defensive-ветке ниже. Ранее на
                    # этой degraded-ветке действовал статический потолок,
                    # который вытеснял единственную тему ЦЕЛИКОМ (пакет «пуст»
                    # → L2 публиковал мета-текст).
                    package_result = build_fallback_package(
                        payload_items, correlation_id=correlation_id,
                        chat_id=chat_id,
                        reason=str(getattr(l1_result, "invalid_reason", None)
                                   or getattr(l1_result, "status", None)
                                   or "l1_unusable"),
                        budget=l2_budget)
                    fallback_used = True
                    if package_result is None:
                        # Пустой payload (0 сообщений после фильтра) — НЕ
                        # failure: существующая empty-семантика (строка 2).
                        if ctx is not None:
                            ctx.status = STATUS_EMPTY
                            ctx.stage = "package"
                            ctx.reason = "l1_empty_payload"
                        return
            else:
                stage = "package"
                if map_payload is not None:
                    # T-4609 (spec §2 B.3; ADR-1028-8 D4/AM-5): FactPackage —
                    # derived view; синтез детерминированный SourceWindow +
                    # semantic map (fragments materialize; chronology; roster;
                    # потолки MAX_FACTS_* через repair_capacity_overflow).
                    from services.summary_fact_view import \
                        build_fact_view_from_map
                    view = build_fact_view_from_map(
                        map_payload, payload_items,
                        chat_id=chat_id, correlation_id=correlation_id)
                    if view.deliverable:
                        package_result = view
                    else:
                        # Defensive (не ожидается): fallback-view → L2 всё
                        # равно вызывается от окна.
                        package_result = build_fallback_package(
                            payload_items, correlation_id=correlation_id,
                            chat_id=chat_id, reason="fact_view_unusable",
                            budget=l2_budget)
                        fallback_used = True
                        if package_result is None:
                            if ctx is not None:
                                ctx.status = STATUS_EMPTY
                                ctx.stage = "package"
                                ctx.reason = "payload_empty"
                            return
                else:
                    package_result = build_fact_package(
                        l1_result, payload_items,
                        correlation_id=correlation_id, budget=l2_budget)
                    if not package_result.deliverable:
                        # Матрица строка 5 (defensive, не ожидается после
                        # (h)): пересборка fallback-пакетом → L2 всё равно
                        # вызывается. ASAP-3.1 (H-ASAP31-1 rework): тот же
                        # вид бюджета (единый resolver, §131/§37) —
                        # fallback-пакет не возвращается на статический
                        # потолок.
                        package_result = build_fallback_package(
                            payload_items, correlation_id=correlation_id,
                            chat_id=chat_id, reason="package_unusable",
                            budget=l2_budget)
                        fallback_used = True
                        if package_result is None:
                            if ctx is not None:
                                ctx.status = STATUS_EMPTY
                                ctx.stage = "package"
                                ctx.reason = "payload_empty"
                            return
            # ASAP-3.1 incident fix 29.09.2026 (EMPTY-PACKAGE GUARD):
            # fallback-пакет, пустой ПО МАТЕРИАЛУ (0 fragments ∧ 0 chronology)
            # при непустом source window, НЕ публикуем мета-текстом через L2 —
            # LEVEL-3 Legacy (published-guard внутри `_legacy_fallback`).
            # T-4608: writer-source ON → пакет — вспомогательный индекс,
            # Writer работает от окна → guard не прыгает в Legacy (not false
            # quality: full window у Writer есть).
            if fallback_used and _package_content_empty(package_result) \
                    and not writer_source:
                logger.warning(
                    "L1_FALLBACK_PACKAGE_EMPTY | run_id=%s | chat_id=%s — "
                    "LEVEL-3 legacy fallback",
                    correlation_id, chat_id)
                if ctx is not None:
                    ctx.stage = "package"
                    ctx.reason = "near_empty_package"
                if await _legacy_fallback("empty_fallback_package"):
                    published = True
                else:
                    if ctx is not None:
                        ctx.status = STATUS_DEGRADED
                        ctx.code = CODE_SUMMARY_GENERATION_FAILED
                return
            # Волна C (T-4425, §50.37/§61.6-каркас): source coverage —
            # first-class поля run state (единый расчёт с Legacy-путём;
            # числа, R17). Потери окна видны в SUMMARY_COMPLETE (coverage=).
            # T-4608/T-4609: writer-source ON → coverage Writer-входа = Full
            # SourceWindow (весь окно доставлено Writer'у; карта/пакет —
            # вспомогательные): 100% честно (никогда не «0/839»).
            if ctx is not None and writer_source:
                ctx.source_total = len(rows)
                ctx.source_considered = len(rows)
                ctx.source_coverage = 100.0
            if ctx is not None and package_result is not None \
                    and getattr(package_result, "package", None):
                try:
                    from services.summary_legacy_fullwindow import (
                        compute_package_coverage,
                    )
                    cov = compute_package_coverage(
                        package_result.package, len(rows))
                    ctx.source_total = cov["source_messages_total"]
                    ctx.source_considered = cov["source_messages_considered"]
                    ctx.source_coverage = cov["coverage_percent"]
                except Exception:      # fail-open
                    pass
                # Волна D (T-4433, §50.30): grade пакета — degraded_package
                # (L1_FALLBACK_PACKAGE) виден в run state/логе честно.
                try:
                    ctx.package_grade = str(
                        (package_result.package.get("service") or {}).get(
                            "package_grade") or "") or None
                    if ctx.package_grade == "degraded":
                        logger.info(
                            "L2_PACKAGE_DEGRADED | run_id=%s | chat_id=%s — "
                            "fallback package (не полноценный semantic)",
                            correlation_id or "none", chat_id)
                except Exception:      # fail-open
                    pass
            stage = "l2"
            # T-4616: checkpoint WRITING (Writer/Reviewer старт). Fail-open.
            try:
                await self._durable_mark(ctx, _srs.STATE_WRITING)
            except Exception:  # pragma: no cover - fail-open
                pass
            service = (package_result.package or {}).get("service") or {}
            # ASAP-3.2 (ADR-1028-5 D8, §39): paged L2 — если редуцированный
            # пакет не влез в бюджет одного вызова, L2 вызывается ПО
            # СТРАНИЦАМ (chained/paged), документы объединяются; НИ ОДИН
            # уникальный элемент пакета не выбрасывается.
            _pages = getattr(package_result, "pages", ()) or ()
            if writer_source and not _pages:
                # T-4609/T-4610 (spec §2 B.3/B.4; ADR-1028-8 D4/AM-4):
                # Writer от Full SourceWindow (FactPackage = derived view —
                # только валидация/roster); Reviewer — окно/slices; bounded
                # revision ×2/budget ≤6 — без изменений (внутри review).
                l2_result = await self._run_writer_source_stage(
                    chat_id, rows, payload_items, map_payload,
                    package_result, service, correlation_id, ctx=ctx,
                    map_unavailable=not getattr(l1_result, "usable", True))
                calls_so_far += 1 + _l2_review_extra_calls(l2_result)
            elif _pages:
                from services.summary_l2_writer import L2Result as _L2Result
                _documents: list = []
                _page_fail = None
                for _page in _pages:
                    _page_result = await run_l2(
                        self.llm, _page, service=service,
                        correlation_id=correlation_id, chat_id=chat_id)
                    calls_so_far += 1
                    if not _page_result.usable:
                        _page_fail = _page_result
                        break
                    _documents.append(_page_result.document)
                if _page_fail is not None:
                    l2_result = _page_fail
                else:
                    _merged_paragraphs: list = []
                    _title = ""
                    _finale = None
                    for _doc in _documents:
                        if not _title:
                            _title = str((_doc or {}).get("title") or "")
                        _merged_paragraphs.extend(
                            (_doc or {}).get("paragraphs") or [])
                        if (_doc or {}).get("finale"):
                            _finale = (_doc or {}).get("finale")
                    _merged_doc = {"schema_version": 1,
                                   "title": _title,
                                   "paragraphs": _merged_paragraphs}
                    if _finale:
                        _merged_doc["finale"] = _finale
                    l2_result = _L2Result(
                        status="ok", document=_merged_doc,
                        invalid_reason=None, usage=None,
                        metrics={"pages": len(_pages)}, duration_ms=0.0)
                logger.info(
                    "L2_PAGED | run_id=%s | chat_id=%s | pages=%d",
                    correlation_id or "none", chat_id, len(_pages))
                # Волна D (ADR D3.3): call budget ≤6 фиксирован для writer=1;
                # paged L2 (k страниц, ASAP-3.2) в бюджет ADR не входит —
                # semantic review на paged-пути НЕ применяется. Bypass не
                # тихий: маркирован в run state (health) и логе.
                if _l2_review_enabled_safe() and ctx is not None:
                    ctx.pipeline_health = "degraded"
                    logger.info(
                        "L2_REVIEW_SKIPPED | run_id=%s | chat_id=%s | "
                        "reason=paged_l2 | pages=%d",
                        correlation_id or "none", chat_id, len(_pages))
            else:
                # ASAP-4 волна D (T-4431/T-4432, ADR D3/D5): master-флаг
                # SUMMARY_L2_REVIEW_ENABLED — ON → bounded review loop
                # (Draft→Validate→Review→≤2 Revision; budget ≤6); OFF →
                # прежний single-call run_l2 БЕТ-В-БИТ (модуль review не
                # импортируется).
                review_on = _l2_review_enabled_safe()
                if review_on:
                    from services.summary_l2_review import run_l2_with_review
                    l2_result = await run_l2_with_review(
                        self.llm, package_result.package, service=service,
                        correlation_id=correlation_id, chat_id=chat_id,
                        ctx=ctx)
                else:
                    l2_result = await run_l2(
                        self.llm, package_result.package, service=service,
                        correlation_id=correlation_id, chat_id=chat_id)
                calls_so_far += 1 + _l2_review_extra_calls(l2_result)
                # Волна E (T-4440): SUMMARY_L2_REVIEW — исход bounded review
                # loop (только при реально запущенном review, calls>0).
                try:
                    from services import pipeline_events
                    pipeline_events.l2_review(
                        correlation_id, chat_id=chat_id,
                        metrics=dict(getattr(l2_result, "metrics", None)
                                     or {}))
                except Exception:  # pragma: no cover
                    pass
            # Волна E (T-4440): SUMMARY_L2_STAGE (ok / unusable+reason).
            try:
                from services import pipeline_events
                _doc_paras = len(((getattr(l2_result, "document", None)
                                   or {}).get("paragraphs")) or [])
                pipeline_events.l2_stage(
                    correlation_id, chat_id=chat_id,
                    usable=bool(getattr(l2_result, "usable", False)),
                    invalid_reason=getattr(l2_result, "invalid_reason", None),
                    duration_ms=getattr(l2_result, "duration_ms", None),
                    paragraphs=_doc_paras)
            except Exception:  # pragma: no cover
                pass
            # T-4616: append-only stage events Writer/Reviewer (§50.54).
            try:
                await self._durable_stage_result(
                    ctx, "l2", "ok" if getattr(l2_result, "usable", False)
                    else "failed",
                    reason=str(getattr(l2_result, "invalid_reason", None)
                               or "") or None)
                _rev_metrics = dict(getattr(l2_result, "metrics", None) or {})
                if _rev_metrics.get("l2_review_iterations") is not None:
                    await self._durable_stage_result(
                        ctx, "l2_review",
                        "degraded" if _rev_metrics.get(
                            "l2_review_degraded") else "ok")
            except Exception:  # pragma: no cover - fail-open
                pass
            if not l2_result.usable:
                # Матрица строка 6: L2 unusable (обычный И fallback-пакет) →
                # LEVEL-3 Legacy. Волна D (ADR-1028-7 D3 SUPERSEDE): после
                # bounded review (≤2 revision) — тот же безопасный исход
                # (l2_review_rejected/l2_review_unusable; §50.2 перечень).
                logger.warning(
                    "L2_ERROR | run_id=%s | chat_id=%s | reason=%s — LEVEL-3 "
                    "legacy fallback",
                    correlation_id, chat_id, l2_result.invalid_reason or "error")
                if ctx is not None:
                    ctx.stage = "l2"
                    ctx.reason = l2_result.invalid_reason or "error"
                    # §50.53: health фиксирует деградацию ДО Legacy —
                    # успешная Legacy-публикация её не сотрёт.
                    ctx.pipeline_health = "degraded"
                if await _legacy_fallback("l2_unusable"):
                    published = True
                else:
                    if ctx is not None:
                        ctx.status = STATUS_DEGRADED
                        ctx.code = CODE_SUMMARY_GENERATION_FAILED
                return
            # Волна D: review_degraded (§50.29/ADR D3.5) — документ
            # опубликован, но run честно помечен деградацией (не success).
            if ctx is not None:
                if int((l2_result.metrics or {}).get(
                        "l2_review_degraded", 0) or 0):
                    ctx.pipeline_health = "degraded"
                if not getattr(ctx, "pipeline_health", None):
                    ctx.pipeline_health = "ok"
            stage = "deliver"
            # T-4616/T-4618 (spec §5 E.1/§6 F.1): checkpoint TEXT_READY —
            # approved text snapshot зафиксирован; cover-ветка ниже
            # подписывается на ЭТОТ документ (text pipeline не регенерируется).
            try:
                await self._durable_mark(ctx, _srs.STATE_TEXT_READY)
            except Exception:  # pragma: no cover - fail-open
                pass
            # T-4624 (spec §7.3; §42 ТЗ): SUMMARY_TEXT_READY в mca_events
            # (Hybrid-путь; этап до обложки/публикации). Fail-open.
            try:
                from services import pipeline_events as _pe
                _pe.text_ready(correlation_id, chat_id=chat_id, stage="l2")
            except Exception:  # pragma: no cover - эмиссия не рвёт
                pass
            document = l2_result.document
            if ctx is not None:
                ctx.paragraphs = len((document or {}).get("paragraphs") or [])
            cover_prompt = normalize_cover_prompt(service.get("cover_prompt"))
            if (fallback_used and not cover_prompt
                    and getattr(settings, "SUMMARY_COVER_FALLBACK_ENABLED", True)
                    and getattr(settings, "SUMMARY_COVER_ARTICLE_ENABLED", True)
                    and _rich_media_supported()):
                # DoD-14 на деградированном пути: обложка LEVEL-2 —
                # детерминированная из заголовка/первой фразы документа
                # (`_derive_fallback_cover_prompt`, 0 LLM).
                first_para = ""
                paras = (document or {}).get("paragraphs") or []
                if paras and isinstance(paras[0], dict):
                    first_para = str(paras[0].get("text") or "")
                cover_prompt = self._derive_fallback_cover_prompt(
                    (str((document or {}).get("title") or "")
                     + ". " + first_para).strip())
            if (cover_prompt
                    and getattr(settings, "SUMMARY_COVER_ARTICLE_ENABLED", True)
                    and _rich_media_supported()):
                # Матрица строки 7/8: cover/rich-отказ → plain полного текста
                # (внутри _publish_rich_document) — НЕ Legacy.
                published = await self._deliver_l2_rich(
                    chat_id, document, cover_prompt, correlation_id, ctx=ctx)
            else:
                if ctx is not None:
                    ctx.cover_status = "unavailable"
                published = await self._deliver_l2_plain(
                    chat_id, document, correlation_id, ctx=ctx)
            if not published:
                # Матрица строка 9: plain-доставка hybrid-текста fail (HTML и
                # text-даунгрейд) → LEVEL-3 Legacy (§9:2289–2291).
                if ctx is not None:
                    ctx.stage = "publish"
                if await _legacy_fallback("delivery_failed"):
                    published = True
                elif ctx is not None and ctx.status != STATUS_FAILED:
                    ctx.status = STATUS_DEGRADED
                    ctx.code = CODE_SUMMARY_GENERATION_FAILED
        except LLMError as exc:
            # Матрица строка 10: непредвиденный LLMError на стадии, которая
            # его не гасит (доставка/обложка) → LEVEL-3 best-effort, если
            # ничего не опубликовано.
            if ctx is not None:
                ctx.fail_from_exc(stage=stage, exc=exc,
                                  code=_generation_code(stage))
            logger.warning("summary: LLM failed | chat_id=%s | error=%s",
                           chat_id, exc)
            if not published and await _legacy_fallback(
                    "hybrid_exception:LLMError"):
                return
            await self._send_ux(chat_id, _UX_LLM_FAILED)
        except _SQLITE_ERRORS:
            if ctx is not None:
                ctx.fail(stage=stage, reason="db_error",
                         error_type="DatabaseError")
            logger.exception("summary: DB failed | chat_id=%s", chat_id)
            await self._send_ux(chat_id, _UX_DB_FAILED)
        except Exception as exc:
            if ctx is not None:
                ctx.fail_from_exc(stage=stage, exc=exc,
                                  code=_generation_code(stage))
            logger.exception("summary: unexpected failure | chat_id=%s", chat_id)
            if not published and await _legacy_fallback(
                    "hybrid_exception:" + type(exc).__name__):
                return
            await self._send_ux(chat_id, _UX_GENERIC_FAILED)

    async def build_test_rows(self, chat_id: int, *, since_ts: int,
                              limit: int | None = None,
                              correlation_id: str | None = None,
                              trigger_message_id: int | None = None) -> dict:
        """ASAP-2.1 (T-3972, контракт (j)): read-only окно для dry-run.

        Аддитивный публичный метод: читает окно **read-only** через
        ``memory.db.get_smart_window`` (без ``compress_and_purge`` /
        ``get_window_messages`` — fire-and-forget бегущего конспекта не
        триггерится). S1/S2 удалены из live-пути (ADR-1028-1 D1/D2) — test path
        НЕ продолжает запускать старую filtering logic: L1 получает полный
        source, packing идёт внутри ``run_l1`` идентично продy. 0 LLM-вызовов,
        0 публикаций, 0 записей в память/досье.

        Возвращает прежний shape для UI (API-форма не менялась):
        ``{"source","filtered","dropped","restored","filter_metrics",
        "source_count","filtered_count","restored_count","limit"}`` — строки
        схемы окна (``sqlite3.Row``), ``filtered = source``, ``dropped``/
        ``restored`` пусты, ``filter_metrics = {}``. Без мутации входа.
        """
        if limit is None:
            limit = int(await _chat_limit(
                chat_id, "limits.summary_max_window_messages",
                hot.get("limits.summary_max_window_messages",
                        settings.SUMMARY_MAX_WINDOW_MESSAGES)))
        db = getattr(self.memory, "db", None)
        source: list = []
        if db is not None:
            rows = await db.get_smart_window(chat_id, int(since_ts), int(limit))
            source = list(rows or [])
        return {
            "source": source,
            "filtered": source,
            "dropped": [],
            "restored": [],
            "filter_metrics": {},
            "source_count": len(source),
            "filtered_count": len(source),
            "restored_count": 0,
            "limit": int(limit),
        }

    async def _deliver_l2_plain(self, chat_id: int, document: dict,
                                correlation_id: str | None = None,
                                ctx=None) -> bool:
        """S6 (ADR-1026-11 D1/D2): обёртка ON-plain — единое ядро §105.

        Имя сохранено (совместимость); доставка/события — в
        :meth:`_publish_plain_document` (тот же канал для OFF и ON).
        ASAP-2 §1: hybrid-plain — БЕЗ send-капа (``max_chunks=None`` —
        полный текст чанками §105); возвращает published.
        """
        return await self._publish_plain_document(
            chat_id, document, correlation_id=correlation_id, ctx=ctx,
            reason="plain")

    async def _record_published_output(self, chat_id: int, message_id,
                                       text: str | None, *,
                                       correlation_id: str | None = None,
                                       source_feature: str = "summary",
                                       output_kind: str = "rich_message"
                                       ) -> None:
        """MCA-22 (C2, T-4287/T-4288; fix round-1 M-4): durable ledger —
        реально ДОСТАВЛЕННАЯ статья/чанки summary (`output_kind=rich_message`).

        Вызывается ТОЛЬКО после успешной send (rich/no-cover/plain-чанки);
        недоставленный draft не записывается (§4: недоставленное ≠ слова
        бота). db — default-binding ledger (`setup_summary`); gate OFF /
        db нет → честный skip. Правка не применима (статьи не редактируются
        ботом). Хеш/текст — стабильный plain-рендер документа."""
        try:
            from services import bot_output_ledger as _bol
            stored = None
            if text:
                stored = str(text)[:20000]
            output_id = await _bol.record_delivered_output(
                None, chat_id=chat_id,
                tg_message_id=(message_id
                               if isinstance(message_id, int) else None),
                text=stored,
                bot_user_id=getattr(self.bot, "id", None),
                output_kind=output_kind, sent_at=int(time.time()),
                correlation_id=correlation_id,
                source_feature=source_feature)
            # T-4617 (ADR-1028-8 D6.2): publication_status → published
            # (после успешной send; result_ref — ledger-факт/telegram id).
            try:
                from services import summary_run_store as srs
                if correlation_id and srs.run_durable_enabled():
                    db = self._run_db()
                    if db is not None:
                        ref = str(message_id) if isinstance(
                            message_id, int) else (
                            _bol.bot_output_source_ref_id(output_id)
                            if output_id else None)
                        await srs.complete_publication(
                            db, correlation_id, result_ref=ref)
            except Exception:  # pragma: no cover - fail-open
                pass
        except Exception:
            logger.warning(
                "[mca22] summary ledger record failed | chat_id=%s",
                chat_id, exc_info=True)

    @staticmethod
    def _document_plain_text(document) -> str | None:
        """Стабильный plain-рендер документа для ledger-текста/хеша."""
        try:
            if not isinstance(document, dict):
                return str(document or "") or None
            from services.summary_article_formatter import format_plain_text
            return format_plain_text(document) or None
        except Exception:
            return None

    async def _publish_plain_document(self, chat_id: int, document,
                                      *, correlation_id: str | None = None,
                                      ctx=None, reason: str = "plain",
                                      max_chunks: int | None = None) -> bool:
        """§105/S6: единое ядро plain-доставки (OFF+ON) + ``PUBLISH_TEXT_*``.

        HTML-чанки по границам абзацев (``chunk_plain_blocks`` ≤4096);
        ``message_id`` первого чанка — в ``PUBLISH_TEXT_COMPLETE`` (§109/SC-20).
        При отказе HTML — финальный даунгрейд ``format_plain_text`` +
        ``chunk_plain_text`` (без разметки, по абзацам, без молчаливой
        обрезки). Финальный провал текста → ``TEXT_FALLBACK_FAILED`` (§106/D5;
        с ASAP-2 §9 за ним — НЕ терминаль: вызывающий hybrid-контур уходит в
        LEVEL-3 Legacy; решение остаётся вызывающему).
        ``max_chunks`` (ASAP-2 контракт (d)): legacy-вызывающий передаёт резолв
        ``limits.max_summary_parts`` — отправляется не более N sendMessage-
        частей (избыток — WARN ``LEGACY_CHUNKS_CAPPED``, не молча);
        hybrid-вызывающий — ``None`` (полный текст чанками).
        Возвращает ``True``, если хотя бы одна часть успешно отправлена
        (published-гейд LEVEL-3), иначе ``False``. События — best-effort,
        R17-safe.
        """
        from services.summary_article_formatter import (
            chunk_plain_blocks,
            chunk_plain_text,
            format_plain_text,
        )
        if not isinstance(document, dict):
            document = {
                "schema_version": 1, "title": "",
                "paragraphs": [{"text": str(document or ""), "emphasis": None}],
            }
        paragraphs = len(document.get("paragraphs") or [])
        started = log_format_start(
            run_id=correlation_id, chat_id=chat_id, channel="plain")
        # T-4617: идемпотентность публикации — PUBLISHING фиксируется ДО
        # отправки; published/reconciled → отправлять нельзя (двойной финал
        # невозможен). Kill-switch OFF → gate None (байт-в-бит).
        try:
            gate = await self._publication_gate(chat_id, correlation_id,
                                                document)
        except Exception:      # pragma: no cover - fail-open
            gate = None
        if gate == "skip":
            log_format_complete(
                run_id=correlation_id, chat_id=chat_id, channel="plain",
                paragraphs=paragraphs, rich_cut=False,
                visible_paragraphs=paragraphs, collapsed_paragraphs=0,
                started=started)
            return True
        publish_started = log_publish_text_start(
            run_id=correlation_id, chat_id=chat_id, reason=reason)
        try:
            chunks = _cap_legacy_chunks(
                chunk_plain_blocks(document, limit=4096), max_chunks,
                run_id=correlation_id, chat_id=chat_id)
            message_id = None
            for index, chunk in enumerate(chunks):
                message = await self._send_text_with_retry(
                    chat_id, chunk, parse_mode="HTML")
                if index == 0:
                    message_id = getattr(message, "message_id", None)
                if index < len(chunks) - 1:
                    await asyncio.sleep(hot.get(
                        "limits.summary_chunk_delay",
                        settings.SUMMARY_CHUNK_DELAY))
            # ASAP-2.1 (T-3986): plain-канал — rich_cut=0, visible=all
            # (полный текст без ката).
            log_format_complete(
                run_id=correlation_id, chat_id=chat_id, channel="plain",
                paragraphs=paragraphs, rich_cut=False,
                visible_paragraphs=paragraphs, collapsed_paragraphs=0,
                started=started)
            log_publish_text_complete(
                run_id=correlation_id, chat_id=chat_id, message_id=message_id,
                reason=reason, started=publish_started)
            if ctx is not None:
                # S8 (ADR-1026-10 D2/D4) + S6 (D6): реальное состояние
                # форматирования и публикации для узлов/§112.
                ctx.format_channel = "plain"
                ctx.format_status = "ok"
                ctx.format_duration_ms = _elapsed_since(started)
                ctx.publish_channel = "text"
                ctx.publish_status = "ok"
                ctx.publish_message_id = (
                    message_id if isinstance(message_id, int) else None)
                ctx.publish_duration_ms = _elapsed_since(publish_started)
            # MCA-22 (fix round-1 M-4): доставленный summary → durable ledger.
            await self._record_published_output(
                chat_id, message_id, self._document_plain_text(document),
                correlation_id=correlation_id)
            return True
        except Exception as exc:
            # §105: HTML-отправка недоступна/упала → финальный даунгрейд в
            # низкоуровневый текст (без разметки); текст не теряется.
            if ctx is not None:
                ctx.format_channel = "plain"
                ctx.format_status = "downgrade"
                ctx.format_duration_ms = _elapsed_since(started)
            log_format_error(
                run_id=correlation_id, chat_id=chat_id, channel="plain",
                reason=type(exc).__name__)
            plain = format_plain_text(document)
            try:
                message_id = None
                chunks = _cap_legacy_chunks(
                    chunk_plain_text(plain, limit=4096), max_chunks,
                    run_id=correlation_id, chat_id=chat_id)
                for index, chunk in enumerate(chunks):
                    message = await self._send_text_with_retry(chat_id, chunk)
                    if index == 0:
                        message_id = getattr(message, "message_id", None)
                    if index < len(chunks) - 1:
                        await asyncio.sleep(hot.get(
                            "limits.summary_chunk_delay",
                            settings.SUMMARY_CHUNK_DELAY))
                log_publish_text_complete(
                    run_id=correlation_id, chat_id=chat_id,
                    message_id=message_id, reason=reason,
                    started=publish_started)
                if ctx is not None:
                    ctx.publish_channel = "text"
                    ctx.publish_status = "ok"
                    ctx.publish_message_id = (
                        message_id if isinstance(message_id, int) else None)
                    ctx.publish_duration_ms = _elapsed_since(publish_started)
                # MCA-22 (fix round-1 M-4): доставленный plain-fallback
                # summary → durable ledger (тот же kind rich_message).
                await self._record_published_output(
                    chat_id, message_id, self._document_plain_text(document),
                    correlation_id=correlation_id)
                return True
            except Exception as exc2:
                # §106/D5: финальная текстовая доставка упала. OFF-контур —
                # прогон failed; hybrid-контур (ASAP-2 §9) — не терминаль:
                # published=False → вызывающий решает про LEVEL-3 Legacy.
                log_publish_text_error(
                    run_id=correlation_id, chat_id=chat_id,
                    error_type=type(exc2).__name__,
                    reason=type(exc2).__name__,
                    http_status=http_status_of(exc2),
                    attempts=attempts_of(exc2),
                    started=publish_started,
                    code=CODE_TEXT_FALLBACK_FAILED)
                if ctx is not None:
                    ctx.publish_channel = "text"
                    ctx.publish_status = "failed"
                    ctx.publish_duration_ms = _elapsed_since(publish_started)
                    ctx.fail(stage="publish", reason=type(exc2).__name__,
                             error_type=type(exc2).__name__,
                             code=CODE_TEXT_FALLBACK_FAILED)
                return False

    async def _deliver_l2_rich(self, chat_id: int, document: dict,
                               cover_prompt: str,
                               correlation_id: str,
                               ctx=None) -> bool:
        """S6 (ADR-1026-11 D1/D2): обёртка ON-rich — единое ядро §101/§102.

        Имя сохранено (совместимость); обложка → ``<h1>`` → абзацы и события
        ``COVER_*``/``FORMAT_*``/``PUBLISH_RICH_*`` — в
        :meth:`_publish_rich_document`. ASAP-2: возвращает published
        (rich-путь Hybrid send-капом НЕ ограничен).
        """
        return await self._publish_rich_document(
            chat_id, document, cover_prompt,
            correlation_id=correlation_id, ctx=ctx)

    async def _publish_rich_document(self, chat_id: int, document: dict,
                                     cover_prompt: str, *,
                                     correlation_id: str | None = None,
                                     ctx=None,
                                     max_chunks: int | None = None) -> bool:
        """§101/§102/S6: единое ядро rich-доставки (OFF+ON).

        Порядок: ``<img src="tg://photo?id=…">`` → **настоящий** ``<h1>`` →
        ``<p>``-абзацы (``format_rich_html``, ``content_format="html"``, §104
        не тронут). B-R1026S6-1/§105: перед отправкой — ``rich_document_limits``
        по **полному** тексту; переполнение rich-лимитов (блоки/символы) не
        срезается молча — WARN с числами (R17-safe, ``reason=rich_*_limit``),
        ``FORMAT_ERROR`` и plain-фолбэк с полным текстом (``reason=rich_overflow``).
        §106/D5: ``COVER_GENERATION_FAILED`` (текст публикуется plain-путём),
        ``RICH_MESSAGE_SEND_FAILED`` (≤1 retry на RetryAfter → plain-фолбэк);
        §108/D6: ``PUBLISH_RICH_*``. События — best-effort, R17-safe; временный
        файл обложки удаляется в ``finally``.
        """
        from services.summary_article_formatter import rich_document_limits
        from services import cover_style_jobs as _csj
        # T-4616: durable run store (обёртки fail-open; OFF → no-op).
        from services import summary_run_store as _srs
        tmp_path = None
        base_path = None
        styled_path = None
        cover_started = None
        fallback_done = False
        cover_outcome = _csj.RESULT_BASE
        cover_reason = ""
        _csj.emit_cover_event(
            _csj.COVER_PIPELINE_START, outcome="start",
            run_id=correlation_id, chat_id=chat_id)
        # ASAP-4 волна B (spec §2 B.1, T-4415; ADR-1028-7 D6): selection
        # snapshot — ЕДИНАЯ точка резолва стиля на run, до base generation
        # и style edit. Kill-switch OFF → None (бит-в-бит прежний контур).
        snapshot = await _csj.selection_stage(chat_id, run_id=correlation_id)
        try:
            style = await self._resolve_cover_style_text(chat_id)
            image_prompt = compose_cover_image_prompt(style, cover_prompt)
            # F12/ADR-1024-4 D2 (UPD2 п.10.1) + T-2508 (hotfix4): доказательство
            # подмешивания стиля — R17-safe, без полного текста промпта (только
            # длины и МАРКЕРЫ содержимого).
            style_text = (style or "").strip()
            visual_text = (cover_prompt or "").strip()
            markers = cover_style_markers(style)
            logger.info(
                "summary cover: prompt composed | style_present=%s | "
                "style_len=%d | visual_len=%d | final_len=%d | "
                "style_is_default=%s | has_comic=%s | has_heading=%s | "
                "chat_id=%s",
                bool(style_text), len(style_text), len(visual_text),
                len(image_prompt), markers["style_is_default"],
                markers["has_comic"], markers["has_heading"], chat_id)
            cover_started = log_cover_start(
                run_id=correlation_id, chat_id=chat_id,
                provider=provider_label())
            # T-4616/T-4618 (spec §6 F.1): checkpoint BASE_COVER.
            try:
                await self._durable_mark(ctx, _srs.STATE_BASE_COVER)
            except Exception:      # pragma: no cover - fail-open
                pass
            try:
                tmp_path, img_reason = await generate_image_verbose(
                    image_prompt, chat_id=chat_id,
                    correlation_id=correlation_id)
            except Exception as exc:
                log_cover_error(
                    run_id=correlation_id, chat_id=chat_id,
                    provider=provider_label(), error_type=type(exc).__name__,
                    reason=type(exc).__name__, started=cover_started,
                    code=CODE_COVER_GENERATION_FAILED)
                if ctx is not None:
                    ctx.cover_status = "unavailable"
                logger.warning(
                    "summary cover: rich fallback | chat_id=%s | error=%s",
                    chat_id, type(exc).__name__)
                _csj.emit_cover_event(
                    _csj.COVER_BASE_FAILED, outcome="failed",
                    level=logging.WARNING, run_id=correlation_id,
                    chat_id=chat_id, fallback=_csj.REASON_BASE_FAILED,
                    reason_code=_csj.REASON_BASE_FAILED)
                # §44 (T-4419): provenance `no_cover` при выбранном стиле.
                await _csj.record_no_cover_provenance(
                    snapshot, summary_run_id=correlation_id)
                fallback_done = True
                return await self._degrade_without_cover(
                    chat_id, document, correlation_id=correlation_id, ctx=ctx,
                    reason="cover_error", max_chunks=max_chunks)
            if not tmp_path:
                # §106: текст готов, обложки нет → degraded публикация (§50/§51).
                provider = provider_label()
                log_cover_complete(
                    run_id=correlation_id, chat_id=chat_id,
                    status="unavailable", started=cover_started,
                    code=CODE_COVER_GENERATION_FAILED)
                if ctx is not None:
                    ctx.cover_status = "unavailable"
                logger.warning(
                    "summary cover: image unavailable (%s) — degraded | "
                    "reason_class=%s | provider=%s | chat_id=%s",
                    img_reason, reason_class(img_reason), provider, chat_id)
                log_external_api(
                    logger, provider=provider, method="post", status=None,
                    reason=img_reason, level=logging.ERROR)
                _csj.emit_cover_event(
                    _csj.COVER_BASE_FAILED, outcome="failed",
                    level=logging.WARNING, run_id=correlation_id,
                    chat_id=chat_id, fallback=_csj.REASON_BASE_FAILED,
                    reason_code=_csj.REASON_BASE_FAILED)
                # §44 (T-4419): provenance `no_cover` при выбранном стиле.
                await _csj.record_no_cover_provenance(
                    snapshot, summary_run_id=correlation_id)
                fallback_done = True
                return await self._degrade_without_cover(
                    chat_id, document, correlation_id=correlation_id, ctx=ctx,
                    reason="cover_unavailable", max_chunks=max_chunks)
            base_path = tmp_path
            log_cover_complete(
                run_id=correlation_id, chat_id=chat_id, status="ok",
                started=cover_started)
            _csj.emit_cover_event(
                _csj.COVER_BASE_SUCCEEDED, outcome="success",
                run_id=correlation_id, chat_id=chat_id)
            if ctx is not None:
                ctx.cover_status = "ok"
            # EXTRA §3.2/§49: optional Style-стадия поверх готовой base cover.
            # T-4616/T-4618: checkpoint STYLE_EDIT (ветка подписана на
            # approved text snapshot — text pipeline не регенерируется).
            try:
                await self._durable_mark(ctx, _srs.STATE_STYLE_EDIT)
            except Exception:      # pragma: no cover - fail-open
                pass
            style_meta = await self._maybe_apply_cover_style(
                chat_id, base_path, correlation_id, cover_prompt=cover_prompt,
                base_style=style, snapshot=snapshot)
            if style_meta and style_meta.get("styled_path"):
                styled_path = style_meta["styled_path"]
                cover_outcome = _csj.RESULT_STYLED
            elif style_meta and style_meta.get("reason") == _csj.REASON_STYLE_FAILED:
                cover_outcome = _csj.RESULT_BASE
                cover_reason = _csj.REASON_STYLE_FAILED
            cover_for_publish = styled_path or base_path
            format_started = log_format_start(
                run_id=correlation_id, chat_id=chat_id, channel="rich")
            publish_started = None
            try:
                media = [build_cover_media(cover_for_publish)]
                rich_plan = rich_document_limits(
                    document, cover_id=SUMMARY_COVER_MEDIA_ID)
                if not rich_plan["fits"]:
                    # B-R1026S6-1 (§105/SC-20): rich-канал не вмещает весь
                    # текст — никакого тихого среза: явный WARN с числами
                    # (R17-safe) и plain-фолбэк с ПОЛНЫМ текстом.
                    logger.warning(
                        "summary rich: document exceeds limits — plain "
                        "fallback | chat_id=%s | reason=%s | paragraphs=%d | "
                        "html_len=%d | max_paragraphs=%d | max_chars=%d",
                        chat_id, rich_plan["reason"], rich_plan["paragraphs"],
                        rich_plan["html_len"], rich_plan["max_paragraphs"],
                        rich_plan["max_chars"])
                    log_format_error(
                        run_id=correlation_id, chat_id=chat_id, channel="rich",
                        reason=rich_plan["reason"])
                    _csj.emit_cover_event(
                        _csj.COVER_PLAIN_FALLBACK, outcome="skipped",
                        run_id=correlation_id, chat_id=chat_id,
                        fallback="rich_overflow")
                    fallback_done = True
                    return await self._plain_fallback(
                        chat_id, document, correlation_id=correlation_id,
                        ctx=ctx, reason="rich_overflow",
                        max_chunks=max_chunks)
                # T-4617: идемпотентность публикации — PUBLISHING до
                # отправки; published/reconciled → не дублируем.
                try:
                    gate = await self._publication_gate(
                        chat_id, correlation_id, document)
                except Exception:      # pragma: no cover - fail-open
                    gate = None
                if gate == "skip":
                    return True
                publish_started = log_publish_rich_start(
                    run_id=correlation_id, chat_id=chat_id)
                message = await self._send_rich_with_retry(
                    chat_id, rich_plan["html"], media)
            except Exception as exc:
                log_format_error(
                    run_id=correlation_id, chat_id=chat_id, channel="rich",
                    reason=type(exc).__name__,
                    code=CODE_RICH_MESSAGE_SEND_FAILED)
                log_publish_rich_error(
                    run_id=correlation_id, chat_id=chat_id,
                    error_type=type(exc).__name__, reason=type(exc).__name__,
                    http_status=http_status_of(exc), attempts=attempts_of(exc),
                    started=publish_started,
                    code=CODE_RICH_MESSAGE_SEND_FAILED)
                if ctx is not None:
                    ctx.publish_channel = "rich"
                    ctx.publish_status = "failed"
                    ctx.publish_duration_ms = _elapsed_since(publish_started)
                _csj.emit_cover_event(
                    _csj.COVER_RICH_PUBLISH_FAILED, outcome="failed",
                    level=logging.WARNING, run_id=correlation_id,
                    chat_id=chat_id, fallback=_csj.REASON_RICH_FAILED)
                _csj.emit_cover_event(
                    _csj.COVER_PLAIN_FALLBACK, outcome="skipped",
                    run_id=correlation_id, chat_id=chat_id,
                    fallback=_csj.REASON_RICH_FAILED)
                fallback_done = True
                return await self._plain_fallback(
                    chat_id, document, correlation_id=correlation_id, ctx=ctx,
                    reason="rich_error", max_chunks=max_chunks)
            message_id = getattr(message, "message_id", None)
            # ASAP-2.1 (T-3986): rich_cut/visible/collapsed — факты cut'а.
            _para_count = len((document or {}).get("paragraphs") or [])
            _cut = _para_count > 1
            log_format_complete(
                run_id=correlation_id, chat_id=chat_id, channel="rich",
                paragraphs=_para_count,
                rich_cut=_cut,
                visible_paragraphs=(1 if _cut else _para_count),
                collapsed_paragraphs=(_para_count - 1 if _cut else 0),
                started=format_started)
            log_publish_rich_complete(
                run_id=correlation_id, chat_id=chat_id, message_id=message_id,
                started=publish_started)
            if ctx is not None:
                # S8 (ADR-1026-10 D2/D4) + S6 (D6): фактические каналы/
                # статусы форматирования и публикации.
                ctx.format_channel = "rich"
                ctx.format_status = "ok"
                ctx.format_duration_ms = _elapsed_since(format_started)
                ctx.publish_channel = "rich"
                ctx.publish_status = "ok"
                ctx.publish_message_id = (
                    message_id if isinstance(message_id, int) else None)
                ctx.publish_duration_ms = _elapsed_since(publish_started)
            logger.info("summary cover: article sent | chat_id=%s", chat_id)
            _csj.emit_cover_event(
                _csj.COVER_RICH_PUBLISH_SUCCEEDED, outcome="success",
                run_id=correlation_id, chat_id=chat_id)
            _classification = _csj.classify_cover_result(
                published_channel="rich", cover_outcome=cover_outcome,
                cover_reason=cover_reason)
            _csj.emit_cover_event(
                _csj.COVER_PIPELINE_DONE, outcome="success",
                run_id=correlation_id, chat_id=chat_id,
                status=_classification["cover_result"],
                fallback=_classification.get("fallback"))
            # MCA-22 (fix round-1 M-4): доставленная rich-статья → ledger.
            await self._record_published_output(
                chat_id, message_id, self._document_plain_text(document),
                correlation_id=correlation_id)
            return True
        except Exception as exc:
            # Защитная ветка (сбой prep до/вне send-блока): тихий plain-фолбэк.
            if ctx is not None:
                ctx.cover_status = "unavailable"
            logger.warning(
                "summary cover: rich fallback | chat_id=%s | error=%s",
                chat_id, type(exc).__name__)
            if not fallback_done:
                fallback_done = True
                return await self._degrade_without_cover(
                    chat_id, document, correlation_id=correlation_id, ctx=ctx,
                    reason="rich_error", max_chunks=max_chunks)
            return False
        finally:
            for _path in (tmp_path, styled_path):
                if _path:
                    try:
                        os.remove(_path)
                    except OSError:
                        pass

    async def _maybe_apply_cover_style(self, chat_id: int, base_image_path: str,
                                       correlation_id: str | None,
                                       cover_prompt: str = "",
                                       base_style: str = "",
                                       snapshot: dict | None = None) -> dict | None:
        """EXTRA §3.2/§49: применить выбранный per-chat Style к base cover.

        REUSE durable-джобы (§42/§43, DoD-25): строка `task_jobs` создаётся
        через `begin_cover_job`, состояние (вкл. `provider_task_id`) сохраняется
        в `task_jobs` на смене стадии, по исходу — `finish_cover_job`; рестарт
        посреди Style-стадии возобновляется из durable-состояния без повторного
        платного task. Возвращает meta `run_style_job` или None (`Без
        дополнительного стиля`/kill-switch OFF/профиль не найден/стадия не
        применима). Fail-open: исключение → None (публикуется base, §49).

        ASAP-4 волна B (spec §2 B.1/B.4, T-4415/T-4419): при ON
        `COVER_STYLE_SNAPSHOT_ENABLED` профиль берётся из run-snapshot'а
        (повторный резолв style ID запрещён); каждый ранний выход — отдельный
        видимый reason (`COVER_STYLE_SKIPPED` + human-причина + provenance
        base_fallback), ничего не молчит. OFF — прежняя тихая цепочка
        бит-в-бит.
        """
        try:
            from services import cover_style_jobs as csj
            if not csj.cover_styles_enabled():
                return None
            if snapshot is None and csj.snapshot_enabled():
                # Страховка для вызовов мимо `_publish_rich_document`:
                # snapshot строится здесь (fail-open, event в комплекте).
                snapshot = await csj.selection_stage(
                    chat_id, run_id=correlation_id)
            if snapshot is not None:
                profile, skip_reason = await csj.profile_for_snapshot(snapshot)
                if skip_reason:
                    # §42–§44: ранний выход виден (event + provenance base),
                    # публикация не ломается; issue counter не расходуется.
                    await csj.report_style_skip(
                        snapshot, summary_run_id=correlation_id,
                        reason=skip_reason)
                    return None
                if not csj.uses_style_stage(profile):
                    # Режим профиля без Style-стадии — не fail: pipeline_mode
                    # виден в COVER_STYLE_SELECTION.
                    return None
            else:
                # COVER_STYLE_SNAPSHOT_ENABLED=OFF — прежний контур (бит-в-бит):
                style_id = await csj.resolve_selected_style_id(chat_id)
                if not style_id:
                    return None
                profile = await csj.load_selected_profile(chat_id)
                if not profile or not profile.get("enabled"):
                    return None
                if not csj.uses_style_stage(profile):
                    return None
            # §42: durable job REUSE `task_jobs` (второй очереди нет).
            db = getattr(self.memory, "db", None)
            job_id, state = await csj.begin_cover_job(
                db, chat_id=chat_id, correlation_id=correlation_id,
                style_id=profile.get("profile_id"),
                summary_run_id=correlation_id,
                payload={"mode": "production"})
            meta = await csj.run_style_job(
                chat_id=chat_id, base_image_path=base_image_path,
                profile=profile, summary_run_id=correlation_id,
                correlation_id=correlation_id, db=db, job_id=job_id,
                state=state, summary_text=cover_prompt,
                base_style_prompt=base_style)
            try:
                outcome = (csj.RESULT_STYLED if meta.get("styled_path")
                           else csj.RESULT_BASE)
                await csj.finish_cover_job(
                    db, job_id, outcome=outcome,
                    reason_code=(meta.get("fail_reason") or None),
                    checkpoint=state)
            except Exception:
                logger.debug(
                    "summary cover: durable job finish failed (fail-open)",
                    exc_info=True)
            return meta
        except Exception:
            logger.warning(
                "summary cover: style stage skipped (fail-open) | chat_id=%s",
                chat_id, exc_info=True)
            return None

    async def _degrade_without_cover(self, chat_id: int, document, *,
                                     correlation_id: str | None = None,
                                     ctx=None, reason: str = "cover_unavailable",
                                     max_chunks: int | None = None) -> bool:
        """§50/§51: базовая обложка не удалась → RichMessage **без** обложки.

        Новый штатный degraded-режим существующего форматтера (§51/§81), не
        второй пайплайн. При OFF kill-switch `COVER_STYLES_ENABLED` поведение
        остаётся baseline-паритетом — plain (§95), не задевая §90 happy path.
        Если Rich недоступен/упал — последний рубеж plain (§52).
        """
        from services import cover_style_jobs as csj
        if (csj.cover_styles_enabled() and csj.rich_degraded_enabled()
                and _rich_media_supported()):
            return await self._publish_rich_without_cover(
                chat_id, document, correlation_id=correlation_id, ctx=ctx,
                reason=reason, max_chunks=max_chunks)
        return await self._plain_fallback(
            chat_id, document, correlation_id=correlation_id, ctx=ctx,
            reason=reason, max_chunks=max_chunks)

    async def _publish_rich_without_cover(self, chat_id: int, document, *,
                                          correlation_id: str | None = None,
                                          ctx=None,
                                          reason: str = "cover_unavailable",
                                          max_chunks: int | None = None) -> bool:
        """§51: RichMessage без cover-блока (media=[]), title/body/cut сохранены.

        §81: успешный degraded-Rich → Summary успешен; ошибка Rich → plain (§52).
        """
        from services.summary_article_formatter import rich_document_limits
        from services import cover_style_jobs as csj
        format_started = log_format_start(
            run_id=correlation_id, chat_id=chat_id, channel="rich")
        publish_started = None
        try:
            rich_plan = rich_document_limits(document, cover_id=None)
            if not rich_plan["fits"]:
                logger.warning(
                    "summary rich(no-cover): document exceeds limits — plain "
                    "fallback | chat_id=%s | reason=%s", chat_id,
                    rich_plan["reason"])
                log_format_error(
                    run_id=correlation_id, chat_id=chat_id, channel="rich",
                    reason=rich_plan["reason"])
                csj.emit_cover_event(
                    csj.COVER_PLAIN_FALLBACK, outcome="skipped",
                    run_id=correlation_id, chat_id=chat_id,
                    fallback="rich_overflow")
                return await self._plain_fallback(
                    chat_id, document, correlation_id=correlation_id, ctx=ctx,
                    reason="rich_overflow", max_chunks=max_chunks)
            # T-4617: идемпотентность публикации (PUBLISHING до отправки).
            try:
                gate = await self._publication_gate(
                    chat_id, correlation_id, document)
            except Exception:      # pragma: no cover - fail-open
                gate = None
            if gate == "skip":
                return True
            publish_started = log_publish_rich_start(
                run_id=correlation_id, chat_id=chat_id)
            # media=[] — валидный «без обложки» (degraded, §51/§81).
            message = await self._send_rich_without_cover_with_retry(
                chat_id, rich_plan["html"])
        except Exception as exc:
            log_format_error(
                run_id=correlation_id, chat_id=chat_id, channel="rich",
                reason=type(exc).__name__, code=CODE_RICH_MESSAGE_SEND_FAILED)
            log_publish_rich_error(
                run_id=correlation_id, chat_id=chat_id,
                error_type=type(exc).__name__, reason=type(exc).__name__,
                http_status=http_status_of(exc), attempts=attempts_of(exc),
                started=publish_started, code=CODE_RICH_MESSAGE_SEND_FAILED)
            if ctx is not None:
                ctx.publish_channel = "rich"
                ctx.publish_status = "failed"
                ctx.publish_duration_ms = _elapsed_since(publish_started)
            csj.emit_cover_event(
                csj.COVER_RICH_PUBLISH_FAILED, outcome="failed",
                level=logging.WARNING, run_id=correlation_id, chat_id=chat_id,
                fallback=csj.REASON_RICH_FAILED)
            csj.emit_cover_event(
                csj.COVER_PLAIN_FALLBACK, outcome="skipped",
                run_id=correlation_id, chat_id=chat_id,
                fallback=csj.REASON_RICH_FAILED)
            return await self._plain_fallback(
                chat_id, document, correlation_id=correlation_id, ctx=ctx,
                reason="rich_error", max_chunks=max_chunks)
        message_id = getattr(message, "message_id", None)
        _para_count = len((document or {}).get("paragraphs") or [])
        _cut = _para_count > 1
        log_format_complete(
            run_id=correlation_id, chat_id=chat_id, channel="rich",
            paragraphs=_para_count, rich_cut=_cut,
            visible_paragraphs=(1 if _cut else _para_count),
            collapsed_paragraphs=(_para_count - 1 if _cut else 0),
            started=format_started)
        log_publish_rich_complete(
            run_id=correlation_id, chat_id=chat_id, message_id=message_id,
            started=publish_started)
        if ctx is not None:
            ctx.cover_status = "unavailable"
            ctx.format_channel = "rich"
            ctx.format_status = "ok"
            ctx.format_duration_ms = _elapsed_since(format_started)
            ctx.publish_channel = "rich"
            ctx.publish_status = "ok"
            ctx.publish_message_id = (
                message_id if isinstance(message_id, int) else None)
            ctx.publish_duration_ms = _elapsed_since(publish_started)
        csj.emit_cover_event(
            csj.COVER_RICH_PUBLISH_SUCCEEDED, outcome="success",
            run_id=correlation_id, chat_id=chat_id, status="degraded")
        classification = csj.classify_cover_result(
            published_channel="rich", cover_outcome=csj.RESULT_NONE,
            cover_reason=csj.REASON_BASE_FAILED)
        csj.emit_cover_event(
            csj.COVER_PIPELINE_DONE, outcome="success",
            run_id=correlation_id, chat_id=chat_id,
            status=classification["cover_result"],
            fallback=classification.get("fallback"))
        logger.info("summary cover: article sent without cover | chat_id=%s",
                    chat_id)
        # MCA-22 (fix round-1 M-4): доставленная rich-статья (no-cover)
        # → durable ledger.
        await self._record_published_output(
            chat_id, message_id, self._document_plain_text(document),
            correlation_id=correlation_id)
        return True


    async def _supervised_generate(self, messages: list[dict], *,
                                   correlation_id: str | None,
                                   step: str) -> str:
        """Один логический LLM-вызов Summary-генератора (T-4612, ADR-1028-8
        D5): при Supervisor ON — через LLMExecutionSupervisor (attempt-
        потолок ≤4 HTTP, watchdog, provider-fallback с capacity re-plan);
        OFF → прежний канал ``llm.generate`` байт-в-бит."""
        from services import summary_llm_supervisor as _sup
        if _sup.supervisor_enabled():
            content, _usage = await _sup.execute_supervised(
                self.llm, messages=messages, operation="legacy",
                correlation_id=correlation_id, chat_id=None,
                module="summary", step=step)
            return content
        return await self.llm.generate(messages, module="summary", step=step,
                                       correlation_id=correlation_id)

    async def _llm_generate(self, payload: list[dict], chat_id: int, *,
                            correlation_id: str | None = None,
                            step: str = "single") -> str | None:
        """Один LLM-вызов саммари с retry-once. ``None`` → молчание (пустой
        ответ), `LLMError` на повторе пробрасывается (R13-ветка внешнего except).

        F7 (ADR-1023-7 D4): `correlation_id`/`step` — аддитивная телеметрия.
        """
        started = time.monotonic()
        # Epic 60 (65.7, T-475): «печатает…» вокруг LLM-точки (manual И cron).
        # Epic 60 (65.1, T-469): LLMBadResponseError (пустой ответ) — молчание
        # ДО retry-once; R13-ветки не тронуты.
        try:
            async with typing_active(self.bot, chat_id):
                raw = await self._supervised_generate(
                    payload, correlation_id=correlation_id, step=step)
        except LLMBadResponseError as exc:
            logger.warning(
                "summary: empty answer — silence | chat_id=%s | error=%s",
                chat_id, exc)
            return None
        except LLMError:
            # Epic 47 (D189, 56.6): A — retry-once (пауза SUMMARY_RETRY_ONCE_PAUSE)
            logger.warning("summary: LLM failed — retry-once | chat_id=%s", chat_id)
            await asyncio.sleep(hot.get("limits.summary_retry_once_pause",
                                        settings.SUMMARY_RETRY_ONCE_PAUSE))
            try:
                started = time.monotonic()   # latency_ms — только повторная попытка
                async with typing_active(self.bot, chat_id):
                    raw = await self._supervised_generate(
                        payload, correlation_id=correlation_id, step=step)
            except LLMBadResponseError as exc:
                # 65.1: пустой ответ на повторе — тоже молчание.
                logger.warning(
                    "summary: empty answer — silence | chat_id=%s | error=%s",
                    chat_id, exc)
                return None
            except LLMError:
                raise                       # C — UX R13 через внешний except
        latency_ms = (time.monotonic() - started) * 1000.0
        # R17 (S10.22-8): логируем только числа/тайминги/класс, без сырого
        # ответа LLM (прецедент `factcheck_service._invoke_llm`).
        logger.info(
            "summary LLM response | chat_id=%s | len=%d | latency_ms=%.0f",
            chat_id, len(raw), latency_ms,
        )
        return raw

    async def _generate_two_call(self, user_content: str, max_symbols: int,
                                 chat_id: int,
                                 correlation_id: str | None = None
                                 ) -> "SummaryDraft | None":
        """System 2 саммари: Редактор → Рассказчик. ``None`` → одиночный путь.

        F6 (ADR-1023-6): возвращает ``SummaryDraft`` (текст + ``cover_prompt`` +
        ``response_mode``); канал Stage-2 — ``rich``, когда обложка реально
        возможна (флаг ON ∧ поддержка media ∧ ``cover_prompt`` ≠ "")."""
        editor_payload = [
            {"role": "system", "content": resolve_prompt(
                "prompts.summary_editor_system_prompt",
                SUMMARY_EDITOR_SYSTEM_PROMPT)},
            {"role": "user", "content": user_content},
        ]
        # T-2484 (ADR-1025-7 D1): таймаут/транзиент Stage-1 больше НЕ роняет
        # всё саммари — фиксируем причину (R17-safe) и уходим на одиночный путь
        # (обложку не теряем — см. `_run`). Повтор ровно один уже выполнен
        # внутри `_llm_generate` (retry-once на LLMError) — границы держим.
        try:
            editor_raw = await self._llm_generate(
                editor_payload, chat_id, correlation_id=correlation_id,
                step="stage1")
        except LLMError as exc:
            reason = ("timeout" if isinstance(exc, LLMTimeoutError)
                      else "llm_error")
            logger.warning(
                "summary system2: stage1 provider failure — fallback | "
                "chat_id=%s | reason=%s | error=%s",
                chat_id, reason, type(exc).__name__)
            return None
        if editor_raw is None:
            # Пустой ответ Stage-1 (`_llm_generate` → None) — тоже фолбэк.
            logger.info(
                "summary system2: stage1 empty answer — fallback | "
                "chat_id=%s | reason=empty", chat_id)
            return None
        parsed, parse_reason = parse_summary_handoff_ex(editor_raw)
        if parsed is None:
            logger.info(
                "summary system2: invalid editor handoff — fallback | "
                "chat_id=%s | reason=%s", chat_id, parse_reason)
            return None
        digest = parsed["digest"]
        response_mode = parsed["response_mode"]
        cover_prompt = parsed.get("cover_prompt", "")
        modes_on = getattr(settings, "SMART_VERBALIZER_MODES_ENABLED", True)
        # F8 (ADR-1023-8): Stage-2 база читается из PG (hot) с fallback на
        # код-канон; kill-switch OFF → прежний до-F3 Рассказчик.
        narrator_template = (
            resolve_prompt("prompts.summary_narrator_system_prompt",
                           SUMMARY_NARRATOR_SYSTEM_PROMPT)
            if modes_on else PREV_SUMMARY_NARRATOR_R1023)
        narrator_base = narrator_template.replace(
            "{max_symbols}", str(max_symbols))
        # F6: канал Stage-2 = rich, только если Article реально возможен
        # (обложка будет запрошена). Иначе — прежний plain-канал.
        rich_eligible = bool(
            cover_prompt
            and getattr(settings, "SUMMARY_COVER_ARTICLE_ENABLED", True)
            and _rich_media_supported())
        channel = "rich" if rich_eligible else "plain"
        # F3 (ADR-1023-3): режимный блок по response_mode + канальный блок.
        # OFF kill-switch → прежний Рассказчик.
        narrator_system = (compose_verbalizer_system(
            narrator_base, response_mode, channel) if modes_on else narrator_base)
        base_messages = [
            {"role": "system", "content": narrator_system},
            {"role": "user", "content": "ВЫЖИМКА (Markdown):\n" + digest},
        ]

        async def _generate(messages):
            return await self._supervised_generate(
                messages, correlation_id=correlation_id, step="stage2")

        # F4 — Рассказчик отдаёт plain-text R11: маркированный список
        # («- …», «1. …») вне жанра → бракуем (правило F6, вторичное).
        # F3/F6 — на plain-канале включается guard от таблиц; на rich
        # (Article, Сценарий Б) таблицы легальны; в режиме deep_research
        # буллиты разрешены (FORMAT_*_BLOCK их требует).
        if modes_on:
            enabled_rules = channel_enabled_rules(
                channel, response_mode, forbid_bullets=True)
        else:
            enabled_rules = DEFAULT_ENABLED_RULES | {"bullet_list"}
        text, stats = await verbalize_validated(
            _generate, base_messages, max_retries=2,
            enabled_rules=enabled_rules,
            dynamic_rules=anticliche_cache.get_rules() or None)
        logger.info(
            "summary system2 narrator | chat_id=%s | mode=%s | channel=%s "
            "| attempts=%d | retries=%d | hits=%d | fallback=%s", chat_id,
            response_mode, channel, stats.get("attempts", 0),
            stats.get("retries", 0), len(stats.get("hits") or []),
            bool(stats.get("fallback")))
        if not text.strip():
            return None
        # S6 (ADR-1026-11 D2/§5.3): заголовок — первая Markdown-строка digest
        # Stage-1 (детерминированно, 0 LLM; пусто → fallback §5.3 в доставке).
        from services.summary_article_formatter import (
            extract_title_from_markdown,
        )
        return SummaryDraft(text=text, cover_prompt=cover_prompt,
                            response_mode=response_mode,
                            title=extract_title_from_markdown(digest))

    # ── Postprocessing ────────────────────────────────────────

    def _resolve_author(self, row) -> str:
        """Epic 28 (T-214-A): алиас побеждает устаревший author_name старых строк."""
        if self.aliases is not None:
            return self.aliases.resolve(
                int(row["user_id"] or 0), (row["author_name"] or None), None
            )
        return row["author_name"] or "кто-то"

    def _format_l2_quote(self, row) -> str:
        """Epic 28 (R28-1): L2-цитата с ре-резолвом автора и маркером репоста."""
        name = self._resolve_author(row)
        if row_get(row, "is_forward"):
            source = (row_get(row, "forward_source") or "").replace('"', "'").strip()
            name = f'{name} (репост из "{source}")' if source else f"{name} (репост)"
        return f'{name}: {row["text"]}'

    @staticmethod
    def _chunk_by_whitespace(text: str, limit: int) -> list[str]:
        """Greedy chunking; splits only on whitespace, never inside a word."""
        if not text:
            return []
        chunks = []
        current = ""
        for word in text.split(" "):
            if not current:
                current = word
            elif len(current) + 1 + len(word) <= limit:
                current += " " + word
            else:
                chunks.append(current)
                current = word
        if current:
            chunks.append(current)
        return chunks

    @staticmethod
    def _extract_keywords(rows: list, top_n: int = 8) -> list[str]:
        counter: dict[str, int] = {}
        for row in rows:
            text = (row["text"] or "").lower()
            for token in _KEYWORD_RE.findall(text):
                if token not in _STOPWORDS:
                    counter[token] = counter.get(token, 0) + 1
        ranked = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
        return [word for word, _ in ranked[:top_n]]

    @staticmethod
    def _compose_user_content(
        xml_context: str,
        l2_quotes: list[str],
        l3_facts: list[str],
        graph_facts: list[str] = [],
        rag_context: str = "",
    ) -> str:
        """10.20 (БЛОК 2.7, ADR-1020-2 п.3): архивные блоки
        (<historical_graph_facts>, <memory>, <facts>) рендерятся КАНОНИЧЕСКИ
        `format_context_item(kind="archive")` — контрастный маркер
        «Архивная справка» (архив ≠ свежее). Подмешивание архива сохраняется
        (R14); escape_xml_text ОБЯЗАТЕЛЕН (review Low-2)."""
        def _archive(line: str) -> str:
            return format_context_item(
                text=escape_xml_text(line), kind="archive")

        parts = []
        if rag_context:                       # Epic 46 (55.5): RAG-контекст ПЕРВЫМ
            parts.append(rag_context)
        if graph_facts:                        # Q8: секция ПЕРВАЯ, до <chat_history>
            parts.append(
                "<historical_graph_facts>\n"
                + "\n".join(_archive(line) for line in graph_facts)
                + "\n</historical_graph_facts>"
            )
        parts.append(xml_context)
        if l2_quotes:
            parts.append("<memory>\n"
                         + "\n".join(_archive(line) for line in l2_quotes)
                         + "\n</memory>")
        if l3_facts:
            parts.append("<facts>\n"
                         + "\n".join(_archive(line) for line in l3_facts)
                         + "\n</facts>")
        return "\n\n".join(parts)

    # ── Sending ───────────────────────────────────────────────

    def _resolve_cover_prompt(self, draft: "SummaryDraft | None", text: str,
                              chat_id: int) -> str:
        """T-2485 (ADR-1025-7 D1, b): visual-промпт обложки для доставки.

        Успешный Stage-1 → промпт Редактора (прежний путь байт-в-байт).
        Фолбэк Stage-1 (``draft is None``) при ``SYSTEM2_SUMMARY_ENABLED`` и
        ``SUMMARY_COVER_FALLBACK_ENABLED`` (env-only, default ON) → обложка
        **не теряется**: детерминированный промпт из текста саммари. OFF/
        rich-unsupported/без обложки → ``""`` (прежний plain-фолбэк, R11) с
        явной R17-safe причиной в логе. Запуск генерации — существующий
        rich-путь (`_deliver_rich`), контракт не меняется."""
        if draft is not None:
            draft_prompt = (draft.cover_prompt or "").strip()
            if draft_prompt:
                return draft_prompt
            # T-2512 (hotfix4, ADR-1025-8 D1): draft есть, но visual-промпт
            # пуст — НЕ теряем обложку молча: переходим в ветку фолбэка ниже
            # (детерминированный промпт + kill-switch/rich-guard).
            logger.warning(
                "summary cover: draft without visual prompt — fallback path | "
                "chat_id=%s | reason=draft_cover_empty | provider=%s",
                chat_id, provider_label())
        if not getattr(settings, "SYSTEM2_SUMMARY_ENABLED", True):
            # Одиночный путь включён осознанно (kill-switch System 2), не фолбэк.
            return ""
        if not getattr(settings, "SUMMARY_COVER_FALLBACK_ENABLED", True):
            # Kill-switch hotfix3 OFF → plain байт-в-байт (прежнее поведение).
            logger.info(
                "summary cover: fallback disabled — plain | chat_id=%s | "
                "reason=fallback_disabled | provider=%s",
                chat_id, provider_label())
            return ""
        if not getattr(settings, "SUMMARY_COVER_ARTICLE_ENABLED", True):
            logger.info(
                "summary cover: fallback path, cover disabled — plain | "
                "chat_id=%s | reason=cover_disabled | provider=%s",
                chat_id, provider_label())
            return ""
        if not _rich_media_supported():
            logger.info(
                "summary cover: fallback path, rich unsupported — plain | "
                "chat_id=%s | reason=rich_unsupported | provider=%s",
                chat_id, provider_label())
            return ""
        prompt = self._derive_fallback_cover_prompt(text)
        if not prompt:
            logger.warning(
                "summary cover: fallback path, empty cover prompt — plain | "
                "chat_id=%s | reason=cover_prompt_empty | provider=%s",
                chat_id, provider_label())
            return ""
        logger.info(
            "summary cover: fallback path — rich with cover | chat_id=%s | "
            "reason=stage1_fallback | prompt_len=%d", chat_id, len(prompt))
        return prompt

    @staticmethod
    def _derive_fallback_cover_prompt(text: str) -> str:
        """Детерминированный visual-промпт обложки из текста саммари (T-2485).

        Без доп. LLM-вызова: корень фолбэка — провайдерские таймауты, поэтому
        лишний вызов того же провайдера ненадёжен и/или зависает. Берём первую
        фразу, снимаем rich-разметку и служебный шиз-постфикс, режем каноном
        ``SUMMARY_COVER_PROMPT_MAX/300``. Никогда не бросает."""
        try:
            plain = downgrade_rich_to_plain(str(text or "")).strip()
            plain = plain.replace(_SHIZ_MARKER, "").strip()
            if not plain:
                return ""
            first = re.split(r"(?<=[.!?…])\s+", plain, maxsplit=1)[0].strip()
            return normalize_cover_prompt(first)
        except Exception:  # pragma: no cover - defensive
            return ""

    async def _deliver_plain(self, chat_id: int, text: str, *,
                             title: str = "",
                             correlation_id: str | None = None,
                             ctx=None, split_delivery: bool = False) -> bool:
        """§105/S6: plain-доставка OFF — единое ядро (не-streaming).

        Стриминг (``SUMMARY_STREAMING_ENABLED``) — существующий механизм без
        изменений (§5.4, ортогонален §105); иначе — детерминированный адаптер
        ``document_from_plain_text`` (0 LLM) → ``_publish_plain_document``
        (``<b>title</b>`` + абзацы, ``parse_mode="HTML"``, чанки по абзацам).
        ASAP-2 контракт (d): OFF/legacy-вызывающий передаёт send-кап
        ``limits.max_summary_parts`` (hot → env); возвращает published.
        T-4611 (spec §33): ``split_delivery=True`` (зона C ON) — split
        delivery БЕЗ потери tail: кап числа чанков не отбрасывает хвост
        (``MAX_SUMMARY_PARTS`` остаётся soft target промпта).
        """
        max_chunks = None if split_delivery else resolve_legacy_max_parts()
        if hot.get("flags.summary_streaming_enabled",
                   settings.SUMMARY_STREAMING_ENABLED):
            await self._send_streaming(chat_id, text, max_chunks=max_chunks,
                                       run_id=correlation_id)
            return True   # Epic 60 (65.6, T-474)
        from services.summary_article_formatter import (
            document_from_plain_text,
        )
        source = downgrade_rich_to_plain(text) if looks_rich(text) else text
        document = document_from_plain_text(source, title=title)
        return await self._publish_plain_document(
            chat_id, document, correlation_id=correlation_id, ctx=ctx,
            reason="plain", max_chunks=max_chunks)

    async def _resolve_cover_style_text(self, chat_id: int) -> str:
        """T-2509 (hotfix4): авторский «Стиль обложки» — scope-корректно.

        ``prompts.*`` — per-chat-переносимые ключи (`ParamSpec.per_chat`), и
        Mini App в контексте выбранного чата сохраняет значение в
        ``chat_params.overrides`` этого чата, а НЕ в глобальный ``bot_settings``.
        Прежде саммари читало только глобальный ``hot.get`` → настроенный стиль
        «терялся» (уходил код-дефолт). Резолв как у алиасов
        (`summary_aliases.build_alias_resolver`): override чата → глобал →
        дефолт. Fail-open (R6): chat_params недоступен → прежний глобальный
        путь. Возвращает уже нормализованный стиль (дефолт — только при пустоте).
        """
        try:
            from services import chat_params
            raw = await chat_params.get_chat_param(
                chat_id, "prompts.summary_cover_style", None)
        except Exception:
            logger.warning(
                "summary cover: per-chat style resolve failed — global | "
                "chat_id=%s", chat_id)
            raw = hot.get("prompts.summary_cover_style", None)
        return resolve_cover_style(raw)

    async def _deliver_rich(self, chat_id: int, text: str,
                            cover_prompt: str,
                            correlation_id: str | None = None,
                            ctx=None, *, title: str = "") -> bool:
        """F6/S6 (ADR-1023-6 §3.4, ADR-1026-11 D2): OFF rich-доставка.

        Текст OFF конвертируется детерминированным адаптером
        ``document_from_plain_text`` (0 LLM) в §99-документ, дальше — единое
        ядро :meth:`_publish_rich_document` (обложка → **настоящий** ``<h1>`` →
        ``<p>``). Тихий фолбэк для пользователя сохраняется: любая ошибка
        генерации/отправки → plain-путь; в лог — WARNING с классом причины и
        провайдером (R17-safe), без дампа промпта. §104 (модель/провайдер/
        ключ/промпт/порядок) не меняется. ASAP-2 контракт (d): сам rich-путь
        капом НЕ ограничен (sendRichMessage ≠ sendMessage); plain-даунгрейд
        этого legacy-контура получает кап ``limits.max_summary_parts``.
        """
        from services.summary_article_formatter import (
            document_from_plain_text,
        )
        source = downgrade_rich_to_plain(text) if looks_rich(text) else text
        document = document_from_plain_text(source, title=title)
        return await self._publish_rich_document(
            chat_id, document, cover_prompt,
            correlation_id=correlation_id, ctx=ctx,
            max_chunks=resolve_legacy_max_parts())

    async def _send_text_with_retry(self, chat_id: int, text: str, **kwargs):
        """§105/D5: одна попытка отправки текста + РОВНО 1 retry на
        ``TelegramRetryAfter`` (чанк ≤2 попытки, без циклов). Возвращает
        результат ``send_text`` (Message-like) для ``message_id`` §109."""
        try:
            return await send_text(self.bot, chat_id, text, **kwargs)
        except TelegramRetryAfter as exc:
            logger.warning(
                "summary: TelegramRetryAfter %.1fs — one retry | chat_id=%s",
                exc.retry_after, chat_id)
            await asyncio.sleep(exc.retry_after)
            return await send_text(self.bot, chat_id, text, **kwargs)

    async def _send_rich_with_retry(self, chat_id: int, text: str,
                                    media: list):
        """Article ровно 1 повтор по ``retry_after``, затем исключение → plain.

        S6 (D2/D5): явный ``content_format="html"`` (готовый Rich HTML
        форматтера, без авто-детектора) и возврат ``Message`` — для
        ``message_id`` в ``PUBLISH_RICH_COMPLETE`` (§109). Rich ≤2 попытки
        (1 retry на ``TelegramRetryAfter``), без циклов.
        """
        try:
            return await send_rich_message(
                self.bot, chat_id, text, media=media,
                cover_id=SUMMARY_COVER_MEDIA_ID, content_format="html")
        except TelegramRetryAfter as exc:
            logger.warning(
                "summary cover: TelegramRetryAfter %.1fs — one retry | "
                "chat_id=%s", exc.retry_after, chat_id)
            await asyncio.sleep(exc.retry_after)
            return await send_rich_message(
                self.bot, chat_id, text, media=media,
                cover_id=SUMMARY_COVER_MEDIA_ID, content_format="html")

    async def _send_rich_without_cover_with_retry(self, chat_id: int, text: str):
        """§51/§81: RichMessage БЕЗ обложки, ≤1 retry по ``RetryAfter``.

        Отдельный helper (не меняет byte-parity `_send_rich_with_retry`
        Legacy-контура): `media=[]` + `cover_id=None` → degraded-публикация.
        """
        try:
            return await send_rich_message(
                self.bot, chat_id, text, media=[],
                cover_id=None, content_format="html")
        except TelegramRetryAfter as exc:
            logger.warning(
                "summary cover: TelegramRetryAfter %.1fs — one retry (no "
                "cover) | chat_id=%s", exc.retry_after, chat_id)
            await asyncio.sleep(exc.retry_after)
            return await send_rich_message(
                self.bot, chat_id, text, media=[],
                cover_id=None, content_format="html")

    async def _plain_fallback(self, chat_id: int, document, *,
                              correlation_id: str | None = None,
                              ctx=None, reason: str = "rich_error",
                              max_chunks: int | None = None) -> bool:
        """Даунгрейд rich → plain (Сценарий Б) и §105-доставка (единое ядро).

        Review iter1 (Medium-2): решение о даунгрейде — по ФАКТИЧЕСКОМУ
        содержимому (``looks_rich``), а не по ``response_mode``: rich-разметка
        могла появиться и в ``serious``/``casual`` (нарушение R11 моделью), и
        тогда она обязана быть снята на plain-канале. Принимает §99-документ
        (ON/новый OFF-путь) либо legacy-текст (совместимость).
        ``max_chunks`` — ASAP-2 контракт (d): legacy-вызывающий передаёт резолв
        parts, hybrid-вызывающий — None (полный текст)."""
        if isinstance(document, dict):
            doc = document
        else:
            source = (downgrade_rich_to_plain(document)
                      if looks_rich(document) else document)
            from services.summary_article_formatter import (
                document_from_plain_text,
            )
            doc = document_from_plain_text(str(source or ""))
        return await self._publish_plain_document(
            chat_id, doc, correlation_id=correlation_id, ctx=ctx,
            reason=reason, max_chunks=max_chunks)

    async def _send_streaming(self, chat_id: int, text: str, *,
                              max_chunks: int | None = None,
                              run_id: str | None = None) -> None:
        """Epic 60 (65.6, T-474): стриминг ТОЛЬКО саммари — placeholder «…» →
        инкрементальные edit_text с накоплением. Темп: приват 1.0с / группа
        3.0с (get_chat; не узнали тип — консервативный групповой).
        «message is not modified» = success; retry_after → сон + РОВНО 1
        повтор, затем drop чанка (финальный edit гарантирует полноту);
        «message is too long» → break в финал/остаток; прочая ошибка edit →
        деградация в _send_chunked. Остаток >4096 — НОВЫМИ сообщениями без
        дублей (сумма без потерь).
        ``max_chunks`` (ASAP-2 контракт (d)) — Legacy-кап sendMessage-частей:
        placeholder считается первой частью, остаток ограничивается
        ``max_chunks − 1`` новыми сообщениями (WARN ``LEGACY_CHUNKS_CAPPED``
        при срезе, без молчаливой потери)."""
        interval = hot.get("limits.summary_stream_edit_interval_group", settings.SUMMARY_STREAM_EDIT_INTERVAL_GROUP)
        try:
            chat = await self.bot.get_chat(chat_id)
            if getattr(chat, "type", "") == "private":
                interval = hot.get("limits.summary_stream_edit_interval_private", settings.SUMMARY_STREAM_EDIT_INTERVAL_PRIVATE)
        except Exception:
            pass                            # не узнали тип — групповой темп
        chunks = self._chunk_by_whitespace(text, 4096)
        if not chunks:
            logger.warning("summary: streaming — empty final text | chat_id=%s",
                           chat_id)
            return
        sent = await send_text(self.bot, chat_id, "…")
        acc, last_text = "", "…"
        for index, chunk in enumerate(chunks):
            # Накопление с разделителем: чанки режутся ПО пробелам (сам
            # разделитель в чанк не входит) — склейка без пробела склеила бы
            # слова на границе 4096. Нормализация пробелов — как в _chunk_by_whitespace.
            acc = chunk if index == 0 else acc + " " + chunk
            new_text = acc if len(acc) <= 4096 else acc[:4096].rstrip() + "…"
            if new_text == last_text:
                continue                    # защита «message is not modified»
            try:
                await edit_text_safe(sent, new_text)
                last_text = new_text
            except TelegramRetryAfter as exc:       # сон + РОВНО 1 повтор, затем drop
                await asyncio.sleep(exc.retry_after)
                try:
                    await edit_text_safe(sent, new_text)
                    last_text = new_text
                except Exception:
                    pass                    # финальный edit гарантирует полноту
            except TelegramBadRequest as exc:
                msg = getattr(exc, "message", "") or ""
                if "message is not modified" in msg:
                    last_text = new_text    # no-op → success (T-459 тема 3)
                elif "message is too long" in msg:
                    break                   # выходим в финал/остаток
                else:
                    logger.warning(
                        "summary: streaming edit failed — degrade | chat_id=%s",
                        chat_id)
                    return await self._send_chunked(
                        chat_id, text, max_chunks=max_chunks, run_id=run_id)
            await asyncio.sleep(interval)
        try:                                # финальный edit — полнота (без «…»)
            if acc[:4096] != last_text.rstrip("…"):
                await edit_text_safe(sent, acc[:4096])
        except Exception:
            logger.warning("summary: streaming final edit failed | chat_id=%s",
                           chat_id)
        if len(text) > 4096:                # остаток — НОВЫМИ сообщениями (без дублей)
            await self._send_chunked(
                chat_id, text[4096:],
                # placeholder-сообщение = первая sendMessage-часть legacy-капа.
                max_chunks=(None if max_chunks is None
                            else max(0, int(max_chunks) - 1)),
                run_id=run_id)
        logger.info("summary: streaming done | chat_id=%s", chat_id)

    async def _send_chunked(self, chat_id: int, text: str, *,
                            max_chunks: int | None = None,
                            run_id: str | None = None) -> None:
        # ASAP-2 контракт (d): legacy plain-доставка отправляет ≤ parts чанков
        # (избыток — WARN LEGACY_CHUNKS_CAPPED, не молча); hybrid — None.
        chunks = _cap_legacy_chunks(
            self._chunk_by_whitespace(text, 4096), max_chunks,
            run_id=run_id, chat_id=chat_id)
        if not chunks:
            logger.warning("summary: empty final text | chat_id=%s", chat_id)
            return
        for index, chunk in enumerate(chunks):
            if len(chunk) > 4096:
                logger.warning(
                    "summary: chunk %d exceeds 4096 chars (%d) | chat_id=%s",
                    index, len(chunk), chat_id,
                )
            await self._send_one_chunk(chat_id, chunk)
            if index < len(chunks) - 1:
                await asyncio.sleep(hot.get("limits.summary_chunk_delay", settings.SUMMARY_CHUNK_DELAY))
        logger.info("summary: chunks_sent=%d | chat_id=%s", len(chunks), chat_id)

    async def _send_one_chunk(self, chat_id: int, chunk: str) -> None:
        try:
            await send_text(self.bot, chat_id, chunk)
        except TelegramRetryAfter as exc:
            logger.warning(
                "summary: TelegramRetryAfter %.1fs — sleeping, one retry | chat_id=%s",
                exc.retry_after, chat_id,
            )
            await asyncio.sleep(exc.retry_after)
            await send_text(self.bot, chat_id, chunk)

    async def _send_ux(self, chat_id: int, text: str) -> None:
        """Send a UX phrase; its own failure must never crash the run."""
        try:
            await send_text(self.bot, chat_id, text)
        except Exception:
            logger.exception("summary: failed to send UX message | chat_id=%s", chat_id)
