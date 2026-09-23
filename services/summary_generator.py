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
from services.summary_context_restore import (
    RESTORE_CHAIN_DEPTH,
    RestoreParams,
    restore_context,
)
from services.summary_filter import FilterParams, filter_window
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
from services.summary_xml import escape_xml_text
from services.thread_chain import collect_thread_chain
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

# S2 (ADR-1026-4 D1/D7): адаптер восстановления дёргает канонический
# `thread_chain.collect_thread_chain` только для «открытых» якорей (reply-цепочка
# уходит за окно / сквозь бот-ответ). Число обходов ограничено (cap по числу
# добавлений), чтобы прогон не деградировал на «звонких» чатах.
RESTORE_CHAIN_CALLS_MAX = 50


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


_SHIZ_MARKER = "самым главным шизом объявляется"
_SHIZ_AT_RE = re.compile(r"(самым главным шизом объявляется\s+)@+")

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
        # S1 (ADR-1026-1 D6/T-3148): аддитивные метрики префильтра (S8 читает
        # при эмиссии узла kind=algorithm; UI/ExecutionGraph здесь не трогаем).
        self._filter_metrics: dict = {}

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
        try:
            await self.memory.compress_and_purge(chat_id)
            rows = await self.memory.get_window_messages(chat_id)
            ctx.source_count = len(rows)
            if not rows:
                if manual:
                    await self._send_ux(chat_id, _UX_EMPTY)     # B4
                logger.info(
                    "summary: empty window | chat_id=%s manual=%s — no LLM call",
                    chat_id, manual,
                )
                ctx.status = STATUS_EMPTY
                return
            # S1 (ADR-1026-1 D6): префильтр входа L1 — строго между чтением
            # окна и сборкой XML. Фильтруется ТОЛЬКО XML-история; все прочие
            # потребители `rows` (RAG/память/graph/memorize) остаются на
            # исходных строках. 0 LLM-вызовов; OFF → байт-в-байт прежний путь.
            xml_rows = rows
            # T-3160 (M-1, spec §6.1/SC-05): мастер-тумблер резолвится per-chat
            # (чат A ≠ чат B), симметрично flags.summary_filter_reply_context_enabled.
            if bool(await _chat_limit(
                    chat_id, "flags.summary_filter_enabled",
                    hot.get("flags.summary_filter_enabled",
                            settings.SUMMARY_FILTER_ENABLED))):
                xml_rows = await self._apply_filter(
                    chat_id, rows, correlation_id, trigger_message_id)
                # S7 (ADR-1026-9 D2): §109-поля SUMMARY_COMPLETE — только из
                # метрик ЭТОГО прогона (run_id), без устаревшего слота fail-open.
                metrics = getattr(self, "_filter_metrics", None) or {}
                metrics = metrics.get(chat_id) or {}
                if metrics.get("run_id") == correlation_id:
                    ctx.saved_count = metrics.get("saved_count")
                    ctx.restored_count = metrics.get("restored_count")
                    # S8 (ADR-1026-10 D2): реальные метрики S1 для узла
                    # `algorithm`/§112 (только числа/коды; R17-safe).
                    ctx.drop_percent = metrics.get("drop_percent")
                    ctx.filter_status = metrics.get("status")
                    ctx.filter_duration_ms = metrics.get("duration_ms")
            # S5 (ADR-1026-7 D5/§80): ON-ветка врезается ПОСЛЕ S1/S2 — L1
            # получает уже отфильтрованный/восстановленный вход (`xml_rows`),
            # а не сырое окно. `trigger_message_id` учтён S1-фильтром выше,
            # `focus` — focus-блоком в L1 (как в legacy-пути). OFF-путь ниже
            # байт-в-байт.
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
                    chat_id, xml_rows, focus, correlation_id, ctx=ctx)
                return
            xml_context = self.xml.build(xml_rows, self.aliases, trigger_message_id)
            keywords = self._extract_keywords(rows)
            l2_rows = await self.memory.search_long_term(
                chat_id, keywords, await _chat_limit(
                    chat_id, "limits.summary_rag_l2_limit",
                    hot.get("limits.summary_rag_l2_limit",
                            settings.SUMMARY_RAG_L2_LIMIT))
            )
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
            if hot.get("flags.graph_rag_enabled", settings.GRAPH_RAG_ENABLED):
                fire_and_forget(
                    self.memory.memorize_facts(
                        chat_id, _build_batch_text(rows, skip_empty=True), "chat_history"),
                    "summary")
            # 10.20 (БЛОК 2.6, ADR-1020-2): ASC-хронология перед рендером.
            rag_context = await self.memory.get_rag_context(
                chat_id, " ".join(keywords), sort_by_timestamp=True)
            user_content = self._compose_user_content(
                xml_context, l2_quotes, l3_facts, graph_facts, rag_context=rag_context
            )
            # Epic 65: фокус «/summary про X» — блок в НАЧАЛО user_content
            # (SIGIR'26: важное — к краям промпта). System-канон R11 НЕ тронут.
            user_content = _apply_focus(user_content, focus)
            # Epic 60 (64.7, T-468): потолок-проверка user_content перед
            # generate — токены (SUMMARY_MAX_CONTEXT_TOKENS, срез С КОНЦА;
            # chars — fallback). Таймер 6ч/крон НЕ меняются.
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
            if kind == "tokens":
                budget = safe_budget(limit)
                if count_tokens(user_content) > budget:
                    logger.warning(
                        "summary: user content truncated | tokens=%d -> %d",
                        count_tokens(user_content), budget)
                    user_content = truncate_to_tokens(user_content, budget)
            elif len(user_content) > limit:
                logger.warning(
                    "summary: user content truncated | chars=%d", len(user_content))
                user_content = user_content[-limit:]
            max_symbols = hot.get("limits.max_summary_parts",
                                  settings.MAX_SUMMARY_PARTS) * 4000 - 200
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
            if getattr(settings, "SYSTEM2_SUMMARY_ENABLED", True):
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
                ctx.status = STATUS_DEGRADED
                ctx.code = CODE_SUMMARY_GENERATION_FAILED
                return
            raw = cleanup_llm_text(raw)                   # Epic 28 (R28-3)
            raw = _strip_safe_html(raw)                   # review iter1 (H2)
            if not raw.strip():
                # Epic 60 (65.1): после cleanup пусто → молчание (без реакции:
                # message_id в manual-ветку не передаётся — 65.1).
                logger.warning(
                    "summary: empty answer after cleanup — silence | chat_id=%s",
                    chat_id)
                ctx.status = STATUS_EMPTY
                # §106/D5: пустой текст после cleanup — класс генерации.
                ctx.code = CODE_SUMMARY_GENERATION_FAILED
                return
            text = self._ensure_shiz_postfix(raw, rows)
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
                await self._deliver_rich(
                    chat_id, text, cover_prompt,
                    correlation_id=correlation_id, ctx=ctx, title=title)
            else:
                ctx.cover_status = "unavailable"
                await self._deliver_plain(
                    chat_id, text, title=title,
                    correlation_id=correlation_id, ctx=ctx)
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
            # карты вызовов (`/api/analytics/execution/latest`): узлы
            # `algorithm`/`format` + §112. Без DDL/persistence; best-effort —
            # ошибка снапшота пайплайн не рвёт и поведение не меняет.
            try:
                from services import execution_graph_source as _exec_graph
                _filter_slot = getattr(self, "_filter_metrics", None) or {}
                _exec_graph.record_run_from_context(
                    ctx, _filter_slot.get(chat_id))
            except Exception:  # pragma: no cover - снапшот не должен ронять прогон
                pass

    async def _hybrid_l2_enabled(self, chat_id: int) -> bool:
        """S5 (ADR-1026-7 D3/D5): kill-switch гибридного L2-пути.

        env-only ``SUMMARY_HYBRID_L2_ENABLED`` (default False) + hot-first
        ``flags.summary_hybrid_l2_enabled`` + per-chat через ``_chat_limit``.
        OFF (default) → прежний ``_generate_two_call`` байт-в-байт; новые
        модули L2 в живом пути не импортируются.
        """
        try:
            return bool(await _chat_limit(
                chat_id, "flags.summary_hybrid_l2_enabled",
                hot.get("flags.summary_hybrid_l2_enabled",
                        getattr(settings, "SUMMARY_HYBRID_L2_ENABLED", False))))
        except Exception:  # pragma: no cover - защитная ветка
            return False

    async def _run_hybrid_l2(self, chat_id: int, rows: list,
                             focus: str | None,
                             correlation_id: str, ctx=None) -> None:
        """S5 (ADR-1026-7 D5/D6): ON-ветка L1 → пакет → L2 → форматтер.

        Вызывается из ``_run`` **после S1/S2** и получает уже
        отфильтрованный/восстановленный ``rows`` (§80 «фильтр → восстановление →
        L1»); ``focus`` учтён как в legacy-пути (focus-блок в L1),
        ``trigger_message_id`` — через S1-фильтр выше. Ровно **2** физических
        LLM-вызова (L1+L2); fail-closed §106: не usable/deliverable вход → L2
        не вызывается; L2-провал → без legacy-фолбэка, публикации нет; текст
        готов, обложки нет → публикуется текст (§105). ON активируется
        владельцем только после live-приёмки Эпика 1; в S5 проверяется на моках.

        S7 (ADR-1026-9 D1/D2): ``ctx`` (необязательный) заполняется для
        ``SUMMARY_COMPLETE``/``SUMMARY_FAILED``; lifecycle эмитит ``_run`` —
        второй пары ``SUMMARY_*`` здесь НЕТ (дубля нет). Прямой вызов без
        ``ctx`` (тесты S5) поведения не меняет.
        """
        # Ленивые импорты: OFF-путь не тянет модули L2 (байт-в-байт).
        from services.summary_context_restore import build_l1_payload
        from services.summary_fact_package import build_fact_package
        from services.summary_l1_clusterizer import run_l1
        from services.summary_l2_writer import run_l2
        # S7: R17-safe модель/провайдер для SUMMARY_FAILED (host, без ключа).
        if ctx is not None:
            ctx.model = str(getattr(self.llm, "_chat_model", "") or "") or None
            ctx.provider = provider_host(
                str(getattr(self.llm, "_base_url", "") or "")) or None
        stage = "l1"
        try:
            l1_result = await run_l1(
                llm=self.llm, rows=rows, chat_id=chat_id,
                correlation_id=correlation_id,
                focus_block=_apply_focus("", focus))
            if ctx is not None:
                ctx.threads = getattr(l1_result, "threads_count", None)
            # §106: не usable L1 → L2 не вызывается, публикации нет.
            if not l1_result.usable:
                logger.warning(
                    "L2_SKIPPED | run_id=%s | chat_id=%s | reason=l1_not_usable",
                    correlation_id, chat_id)
                if ctx is not None:
                    ctx.status = STATUS_DEGRADED
                    ctx.stage = "l1"
                    ctx.reason = getattr(l1_result, "invalid_reason", None) \
                        or getattr(l1_result, "status", None)
                    ctx.code = CODE_SUMMARY_GENERATION_FAILED
                return
            stage = "package"
            payload_items = build_l1_payload(rows, chat_id)
            package_result = build_fact_package(
                l1_result, payload_items, correlation_id=correlation_id)
            if not package_result.deliverable:
                logger.warning(
                    "L2_SKIPPED | run_id=%s | chat_id=%s | reason=package_%s",
                    correlation_id, chat_id, package_result.reason or "empty")
                if ctx is not None:
                    ctx.status = STATUS_DEGRADED
                    ctx.stage = "package"
                    ctx.reason = package_result.reason or "not_deliverable"
                    ctx.code = CODE_SUMMARY_GENERATION_FAILED
                return
            stage = "l2"
            service = (package_result.package or {}).get("service") or {}
            l2_result = await run_l2(
                self.llm, package_result.package, service=service,
                correlation_id=correlation_id, chat_id=chat_id)
            if not l2_result.usable:
                # §106: L2-провал → без legacy-фолбэка (3-й вызов запрещён).
                logger.warning(
                    "L2_ERROR | run_id=%s | chat_id=%s | reason=%s — не публикуем",
                    correlation_id, chat_id, l2_result.invalid_reason or "error")
                if ctx is not None:
                    ctx.status = STATUS_DEGRADED
                    ctx.stage = "l2"
                    ctx.reason = l2_result.invalid_reason or "error"
                    ctx.code = CODE_SUMMARY_GENERATION_FAILED
                return
            stage = "deliver"
            document = l2_result.document
            if ctx is not None:
                ctx.paragraphs = len((document or {}).get("paragraphs") or [])
            cover_prompt = normalize_cover_prompt(service.get("cover_prompt"))
            if (cover_prompt
                    and getattr(settings, "SUMMARY_COVER_ARTICLE_ENABLED", True)
                    and _rich_media_supported()):
                await self._deliver_l2_rich(
                    chat_id, document, cover_prompt, correlation_id, ctx=ctx)
            else:
                if ctx is not None:
                    ctx.cover_status = "unavailable"
                await self._deliver_l2_plain(
                    chat_id, document, correlation_id, ctx=ctx)
        except LLMError as exc:
            if ctx is not None:
                ctx.fail_from_exc(stage=stage, exc=exc,
                                  code=_generation_code(stage))
            logger.warning("summary: LLM failed | chat_id=%s | error=%s",
                           chat_id, exc)
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
            await self._send_ux(chat_id, _UX_GENERIC_FAILED)

    async def build_test_rows(self, chat_id: int, *, since_ts: int,
                              limit: int | None = None,
                              correlation_id: str | None = None,
                              trigger_message_id: int | None = None) -> dict:
        """S9 (ADR-1026-8 D2): read-only окно + S1/S2 для dry-run тест-прогона.

        Аддитивный публичный метод (тело ``_run``/``_run_hybrid_l2`` НЕ
        меняется): читает окно **read-only** через
        ``memory.db.get_smart_window`` (без ``compress_and_purge`` /
        ``get_window_messages`` — fire-and-forget бегущего конспекта не
        триггерится), применяет существующие ``_apply_filter`` (S1) и
        ``_restore`` (S2) без дублирования резолва параметров. 0 LLM-вызовов,
        0 публикаций, 0 записей в память/досье.

        Возвращает ``{"source","filtered","dropped","restored",
        "filter_metrics","source_count","filtered_count","restored_count",
        "limit"}`` — строки схемы окна (``sqlite3.Row``), без мутации входа.
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
        filtered = source
        filter_metrics: dict = {}
        if source:
            # L-R1026S9-5: сброс слота перед вызовом — fail-open ветка
            # `_apply_filter` его не перезаписывает, поэтому иначе в отчёт
            # тест-прогона могли попасть устаревшие метрики прошлого прогона.
            self._filter_metrics.pop(chat_id, None)
            filtered = list(await self._apply_filter(
                chat_id, source, correlation_id, trigger_message_id) or [])
            filter_metrics = dict(self._filter_metrics.get(chat_id) or {})
        source_ids = {id(row) for row in source}
        filtered_ids = {id(row) for row in filtered}
        dropped = [row for row in source if id(row) not in filtered_ids]
        restored = [row for row in filtered if id(row) not in source_ids]
        return {
            "source": source,
            "filtered": filtered,
            "dropped": dropped,
            "restored": restored,
            "filter_metrics": filter_metrics,
            "source_count": len(source),
            "filtered_count": len(filtered),
            "restored_count": int(
                filter_metrics.get("restored_count") or len(restored)),
            "limit": int(limit),
        }

    async def _deliver_l2_plain(self, chat_id: int, document: dict,
                                correlation_id: str | None = None,
                                ctx=None) -> None:
        """S6 (ADR-1026-11 D1/D2): обёртка ON-plain — единое ядро §105.

        Имя сохранено (совместимость); доставка/события — в
        :meth:`_publish_plain_document` (тот же канал для OFF и ON).
        """
        await self._publish_plain_document(
            chat_id, document, correlation_id=correlation_id, ctx=ctx,
            reason="plain")

    async def _publish_plain_document(self, chat_id: int, document,
                                      *, correlation_id: str | None = None,
                                      ctx=None, reason: str = "plain") -> None:
        """§105/S6: единое ядро plain-доставки (OFF+ON) + ``PUBLISH_TEXT_*``.

        HTML-чанки по границам абзацев (``chunk_plain_blocks`` ≤4096);
        ``message_id`` первого чанка — в ``PUBLISH_TEXT_COMPLETE`` (§109/SC-20).
        При отказе HTML — финальный даунгрейд ``format_plain_text`` +
        ``chunk_plain_text`` (без разметки, по абзацам, без молчаливой
        обрезки). Финальный провал текста → ``TEXT_FALLBACK_FAILED`` и прогон
        ``SUMMARY_FAILED`` (§106/D5). События — best-effort, R17-safe.
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
        publish_started = log_publish_text_start(
            run_id=correlation_id, chat_id=chat_id, reason=reason)
        try:
            chunks = chunk_plain_blocks(document, limit=4096)
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
            log_format_complete(
                run_id=correlation_id, chat_id=chat_id, channel="plain",
                paragraphs=paragraphs, started=started)
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
                chunks = chunk_plain_text(plain, limit=4096)
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
            except Exception as exc2:
                # §106/D5: финальная текстовая доставка упала → прогон failed.
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

    async def _deliver_l2_rich(self, chat_id: int, document: dict,
                               cover_prompt: str,
                               correlation_id: str,
                               ctx=None) -> None:
        """S6 (ADR-1026-11 D1/D2): обёртка ON-rich — единое ядро §101/§102.

        Имя сохранено (совместимость); обложка → ``<h1>`` → абзацы и события
        ``COVER_*``/``FORMAT_*``/``PUBLISH_RICH_*`` — в
        :meth:`_publish_rich_document`.
        """
        await self._publish_rich_document(
            chat_id, document, cover_prompt,
            correlation_id=correlation_id, ctx=ctx)

    async def _publish_rich_document(self, chat_id: int, document: dict,
                                     cover_prompt: str, *,
                                     correlation_id: str | None = None,
                                     ctx=None) -> None:
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
        tmp_path = None
        cover_started = None
        fallback_done = False
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
                fallback_done = True
                return await self._plain_fallback(
                    chat_id, document, correlation_id=correlation_id, ctx=ctx,
                    reason="cover_error")
            if not tmp_path:
                # §106: текст готов, обложки нет → публикуем текст (§105).
                provider = provider_label()
                log_cover_complete(
                    run_id=correlation_id, chat_id=chat_id,
                    status="unavailable", started=cover_started,
                    code=CODE_COVER_GENERATION_FAILED)
                if ctx is not None:
                    ctx.cover_status = "unavailable"
                logger.warning(
                    "summary cover: image unavailable (%s) — plain fallback | "
                    "reason_class=%s | provider=%s | chat_id=%s",
                    img_reason, reason_class(img_reason), provider, chat_id)
                log_external_api(
                    logger, provider=provider, method="post", status=None,
                    reason=img_reason, level=logging.ERROR)
                fallback_done = True
                return await self._plain_fallback(
                    chat_id, document, correlation_id=correlation_id, ctx=ctx,
                    reason="cover_unavailable")
            log_cover_complete(
                run_id=correlation_id, chat_id=chat_id, status="ok",
                started=cover_started)
            if ctx is not None:
                ctx.cover_status = "ok"
            format_started = log_format_start(
                run_id=correlation_id, chat_id=chat_id, channel="rich")
            publish_started = None
            try:
                media = [build_cover_media(tmp_path)]
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
                    fallback_done = True
                    return await self._plain_fallback(
                        chat_id, document, correlation_id=correlation_id,
                        ctx=ctx, reason="rich_overflow")
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
                fallback_done = True
                return await self._plain_fallback(
                    chat_id, document, correlation_id=correlation_id, ctx=ctx,
                    reason="rich_error")
            message_id = getattr(message, "message_id", None)
            log_format_complete(
                run_id=correlation_id, chat_id=chat_id, channel="rich",
                paragraphs=len((document or {}).get("paragraphs") or []),
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
        except Exception as exc:
            # Защитная ветка (сбой prep до/вне send-блока): тихий plain-фолбэк.
            if ctx is not None:
                ctx.cover_status = "unavailable"
            logger.warning(
                "summary cover: rich fallback | chat_id=%s | error=%s",
                chat_id, type(exc).__name__)
            if not fallback_done:
                fallback_done = True
                return await self._plain_fallback(
                    chat_id, document, correlation_id=correlation_id, ctx=ctx,
                    reason="rich_error")
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    async def _apply_filter(self, chat_id: int, rows: list,
                            correlation_id: str | None,
                            trigger_message_id: int | None) -> list:
        """S1 (ADR-1026-1 D4/D6) + S2 (ADR-1026-4 D1/D6): префильтр входа L1 и
        детерминированное восстановление контекста.

        Возвращает строки для XML-истории: ``RestoreResult.kept`` при ON
        (S1 ``kept`` ∪ добавленные) либо ``FilterResult.kept`` при OFF /
        fail-open. Fail-open: любая ошибка → WARNING ``FILTER_ERROR`` /
        ``RESTORE_ERROR`` и безопасный вход (Саммари работает, тихой потери
        нет). 0 LLM-вызовов. Метрики §109 кладутся в аддитивную структуру
        ``self._filter_metrics`` (S8); в логи идут только числа/коды/``run_id``
        (R17/R18).
        """
        try:
            params = FilterParams(
                min_weight=await _chat_limit(
                    chat_id, "limits.summary_filter_min_weight",
                    hot.get("limits.summary_filter_min_weight",
                            settings.SUMMARY_FILTER_MIN_WEIGHT)),
                min_words_for_bonus=await _chat_limit(
                    chat_id, "limits.summary_filter_min_words_for_bonus",
                    hot.get("limits.summary_filter_min_words_for_bonus",
                            settings.SUMMARY_FILTER_MIN_WORDS_FOR_BONUS)),
                burst_window_seconds=await _chat_limit(
                    chat_id, "limits.summary_filter_burst_window_seconds",
                    hot.get("limits.summary_filter_burst_window_seconds",
                            settings.SUMMARY_FILTER_BURST_WINDOW_SECONDS)),
                min_burst_density=await _chat_limit(
                    chat_id, "limits.summary_filter_min_burst_density",
                    hot.get("limits.summary_filter_min_burst_density",
                            settings.SUMMARY_FILTER_MIN_BURST_DENSITY)),
                reply_context_enabled=bool(await _chat_limit(
                    chat_id, "flags.summary_filter_reply_context_enabled",
                    hot.get("flags.summary_filter_reply_context_enabled",
                            settings.SUMMARY_FILTER_REPLY_CONTEXT_ENABLED))),
            )
            # S2 (ADR-1026-4 D4): тот же ключ — мастер-гейт всего восстановления
            # (OFF → S2 не вызывается, XML-вход байт-в-байт равен S1-выходу).
            reply_context_enabled = bool(params.reply_context_enabled)
            # L-R1026S1-1: sentinel-нормализация потолка токенов перед бюджетом
            # §93 (`0`/`None` → дефолт, `-1` → потолок «безлимита»), как в
            # resolve_chat_limit/_run; иначе нарезка/бюджет вырождаются при
            # per-chat override.
            token_limit = resolve_context_tokens(
                await _chat_limit(
                    chat_id, "limits.summary_max_context_tokens",
                    hot.get("limits.summary_max_context_tokens",
                            settings.SUMMARY_MAX_CONTEXT_TOKENS)),
                _SUMMARY_CONTEXT_TOKEN_DEFAULT)
            char_limit = await _chat_limit(
                chat_id, "limits.summary_max_context_chars",
                hot.get("limits.summary_max_context_chars",
                        settings.SUMMARY_MAX_CONTEXT_CHARS))
            logger.info(
                "summary filter: event=FILTER_START | run_id=%s chat_id=%s "
                "source_count=%d", correlation_id, chat_id, len(rows))
            result = filter_window(
                rows, params, bot_id=getattr(self.bot, "id", None),
                trigger_message_id=trigger_message_id,
                token_limit=token_limit, char_limit=char_limit)
            # S2 (ADR-1026-4 D6): врезка строго между `filter_window` и
            # `xml.build`; `effective` нужен только для метрик/логов (D1).
            xml_rows = result.kept
            effective = result
            restore_metrics = None
            if result.status == "error":
                logger.warning(
                    "summary filter: event=FILTER_ERROR | run_id=%s chat_id=%s "
                    "source_count=%d duration_ms=%.1f — fail-open (unfiltered)",
                    correlation_id, chat_id, result.source_count,
                    result.duration_ms)
            else:
                if reply_context_enabled:
                    xml_rows, effective, restore_metrics = await self._restore(
                        chat_id, rows, result, correlation_id, token_limit,
                        char_limit)
                logger.info(
                    "summary filter: event=FILTER_COMPLETE | run_id=%s chat_id=%s "
                    "source_count=%d saved_count=%d restored_count=%d "
                    "drop_percent=%.1f status=%s duration_ms=%.1f",
                    correlation_id, chat_id, result.source_count,
                    result.saved_count, effective.restored_count,
                    result.drop_percent, result.status, result.duration_ms)
                if result.status == "empty_fallback":
                    logger.warning(
                        "summary filter: event=FILTER_EMPTY_FALLBACK | "
                        "run_id=%s chat_id=%s source_count=%d",
                        correlation_id, chat_id, result.source_count)
            # Аддитивные метрики для §111/§112 (S8) — без узлов ExecutionGraph.
            metrics = {
                "run_id": correlation_id,
                "source_count": result.source_count,
                "saved_count": result.saved_count,
                "restored_count": effective.restored_count,
                "drop_percent": result.drop_percent,
                "duration_ms": result.duration_ms,
                "status": result.status,
                "budget": result.budget,
            }
            # S2-метрики добавляются только когда восстановление реально
            # выполнялось: при OFF `_filter_metrics` байт-в-байт как у S1.
            if restore_metrics is not None:
                metrics.update(restore_metrics)
            self._filter_metrics[chat_id] = metrics
            return xml_rows
        except Exception:
            logger.warning(
                "summary filter: event=FILTER_ERROR | run_id=%s chat_id=%s — "
                "fail-open (unfiltered)", correlation_id, chat_id,
                exc_info=True)
            return rows

    async def _restore(self, chat_id: int, rows: list, result,
                       correlation_id: str | None, token_limit,
                       char_limit) -> tuple:
        """S2 (ADR-1026-4 D1/D3/D6): восстановление контекста после S1.

        Возвращает ``(xml_rows, effective_result, metrics|None)``. Fail-open:
        любая ошибка (в т.ч. БД/цепочка) → S1-выход ``result.kept`` + WARNING
        ``RESTORE_ERROR``; ``kept`` не теряется никогда. 0 LLM-вызовов.
        """
        try:
            rparams = RestoreParams(
                context_neighbors=await _chat_limit(
                    chat_id, "limits.summary_filter_context_neighbors",
                    hot.get("limits.summary_filter_context_neighbors",
                            settings.SUMMARY_FILTER_CONTEXT_NEIGHBORS)),
                context_max_messages=await _chat_limit(
                    chat_id, "limits.summary_filter_context_max_messages",
                    hot.get("limits.summary_filter_context_max_messages",
                            settings.SUMMARY_FILTER_CONTEXT_MAX_MESSAGES)),
            )
            bot_id = getattr(self.bot, "id", None)
            extra_parents = await self._collect_extra_parents(
                chat_id, result.kept, rows, bot_id)
            logger.info(
                "summary filter: event=RESTORE_START | run_id=%s chat_id=%s "
                "kept_count=%d extra_parents=%d",
                correlation_id, chat_id, len(result.kept), len(extra_parents))
            restore = restore_context(
                result.kept, result.dropped, rows, rparams,
                extra_parents=extra_parents, token_limit=token_limit,
                char_limit=char_limit, bot_id=bot_id)
            if restore.status == "error":
                logger.warning(
                    "summary filter: event=RESTORE_ERROR | run_id=%s chat_id=%s "
                    "duration_ms=%.1f — fail-open (S1 output)",
                    correlation_id, chat_id, restore.duration_ms)
            else:
                logger.info(
                    "summary filter: event=RESTORE_COMPLETE | run_id=%s "
                    "chat_id=%s status=%s restored_count=%d parent_count=%d "
                    "neighbor_count=%d skipped_count=%d budget_kind=%s "
                    "budget_fits=%s duration_ms=%.1f",
                    correlation_id, chat_id, restore.status,
                    restore.restored_count, restore.parent_count,
                    restore.neighbor_count, len(restore.skipped_ids),
                    restore.budget.get("kind"), restore.budget.get("fits"),
                    restore.duration_ms)
            metrics = {
                "restored_count": restore.restored_count,
                "parent_count": restore.parent_count,
                "neighbor_count": restore.neighbor_count,
                "skipped_count": len(restore.skipped_ids),
                "restore_status": restore.status,
                "restore_budget": restore.budget,
            }
            if restore.status == "error":
                # Внутренний сбой core — S1-выход (тихой потери нет).
                return result.kept, result, metrics
            effective = dataclasses.replace(
                result, kept=restore.kept,
                restored_count=restore.restored_count)
            return restore.kept, effective, metrics
        except Exception:
            logger.warning(
                "summary filter: event=RESTORE_ERROR | run_id=%s chat_id=%s — "
                "fail-open (S1 output)", correlation_id, chat_id, exc_info=True)
            return result.kept, result, None

    async def _collect_extra_parents(self, chat_id: int, kept: list,
                                     window: list, bot_id) -> list:
        """S2 (ADR-1026-4 D1/D7): родители **вне окна / сквозь бот-ответы**.

        Переиспользует канонический ``thread_chain.collect_thread_chain``
        (вторая реализация обхода цепочки не создаётся); обход выполняется
        только для «открытых» якорей (цепочка уходит за пределы окна) и
        ограничен ``RESTORE_CHAIN_CALLS_MAX``. Возвращает строки схемы окна,
        fail-open → ``[]``.
        """
        db = getattr(self.memory, "db", None)
        if db is None:
            return []
        win_by_tg: dict = {}
        for row in window or []:
            tg = row_get(row, "tg_message_id")
            if tg is not None and tg not in win_by_tg:
                win_by_tg[tg] = row
        extra: dict = {}
        calls = 0
        for anchor in kept or []:
            if calls >= RESTORE_CHAIN_CALLS_MAX:
                break
            if not self._is_open_anchor(anchor, win_by_tg):
                continue
            tg = row_get(anchor, "tg_message_id")
            if tg is None:
                continue
            calls += 1
            try:
                chain = await collect_thread_chain(
                    db, chat_id, tg, RESTORE_CHAIN_DEPTH)
            except Exception:
                logger.warning(
                    "summary filter: thread chain failed — skip anchor | "
                    "chat_id=%s", chat_id, exc_info=True)
                continue
            for item in chain:
                if getattr(item, "is_bot", False):
                    continue
                item_tg = _chain_tg_id(getattr(item, "item_id", ""))
                if item_tg is None or item_tg in win_by_tg:
                    continue
                try:
                    row = await db.get_smart_message_by_tg_id(chat_id, item_tg)
                except Exception:
                    logger.warning(
                        "summary filter: thread chain row read failed | "
                        "chat_id=%s", chat_id, exc_info=True)
                    continue
                if row is None:
                    continue
                rid = row_get(row, "id")
                if rid is not None and rid not in extra:
                    extra[rid] = row
        return list(extra.values())

    @staticmethod
    def _is_open_anchor(anchor, win_by_tg) -> bool:
        """Reply-цепочка якоря уходит за пределы окна (или сквозь бот-ответ)?

        Чистая in-memory проверка по окну (без БД): обход ``reply_to_id`` до
        корня; отсутствие родителя в окне → нужен ``collect_thread_chain``.
        """
        current = anchor
        for _ in range(max(0, RESTORE_CHAIN_DEPTH)):
            parent_tg = row_get(current, "reply_to_id")
            if parent_tg is None:
                return False
            parent = win_by_tg.get(parent_tg)
            if parent is None:
                return True
            current = parent
        return False

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
                raw = await self.llm.generate(
                    payload, module="summary", step=step,
                    correlation_id=correlation_id)
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
                    raw = await self.llm.generate(
                        payload, module="summary", step=step,
                        correlation_id=correlation_id)
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
            return await self.llm.generate(
                messages, module="summary", step="stage2",
                correlation_id=correlation_id)

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

    def _ensure_shiz_postfix(self, text: str, rows: list) -> str:
        """Guarantee the 'самым главным шизом объявляется …' postfix (A14)."""
        text = text or ""
        if _SHIZ_MARKER in text:
            # PM note: strip '@' if the LLM wrote the name with it
            return _SHIZ_AT_RE.sub(r"\1", text)
        name = SummaryGenerator._most_active_author(rows, getattr(self, "aliases", None))
        text = text.rstrip()
        if text:
            text += "\n"
        return text + f"самым главным шизом объявляется {name}"

    @staticmethod
    def _most_active_author(rows: list, aliases=None) -> str:
        counter: dict[str, int] = {}
        for row in rows:
            stored = (row["author_name"] or "").strip().lstrip("@")
            if aliases is not None:
                # Epic 28 (T-214-B): заданный алиас побеждает сохранённое имя
                name = aliases.resolve(int(row["user_id"] or 0), stored or None, None)
            else:
                name = stored
            if name:
                counter[name] = counter.get(name, 0) + 1
        if not counter:
            return "кто-то"
        return sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]

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
                             ctx=None) -> None:
        """§105/S6: plain-доставка OFF — единое ядро (не-streaming).

        Стриминг (``SUMMARY_STREAMING_ENABLED``) — существующий механизм без
        изменений (§5.4, ортогонален §105); иначе — детерминированный адаптер
        ``document_from_plain_text`` (0 LLM) → ``_publish_plain_document``
        (``<b>title</b>`` + абзацы, ``parse_mode="HTML"``, чанки по абзацам).
        """
        if hot.get("flags.summary_streaming_enabled",
                   settings.SUMMARY_STREAMING_ENABLED):
            await self._send_streaming(chat_id, text)   # Epic 60 (65.6, T-474)
            return
        from services.summary_article_formatter import (
            document_from_plain_text,
        )
        source = downgrade_rich_to_plain(text) if looks_rich(text) else text
        document = document_from_plain_text(source, title=title)
        await self._publish_plain_document(
            chat_id, document, correlation_id=correlation_id, ctx=ctx,
            reason="plain")

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
                            ctx=None, *, title: str = "") -> None:
        """F6/S6 (ADR-1023-6 §3.4, ADR-1026-11 D2): OFF rich-доставка.

        Текст OFF конвертируется детерминированным адаптером
        ``document_from_plain_text`` (0 LLM) в §99-документ, дальше — единое
        ядро :meth:`_publish_rich_document` (обложка → **настоящий** ``<h1>`` →
        ``<p>``). Тихий фолбэк для пользователя сохраняется: любая ошибка
        генерации/отправки → plain-путь; в лог — WARNING с классом причины и
        провайдером (R17-safe), без дампа промпта. §104 (модель/провайдер/
        ключ/промпт/порядок) не меняется.
        """
        from services.summary_article_formatter import (
            document_from_plain_text,
        )
        source = downgrade_rich_to_plain(text) if looks_rich(text) else text
        document = document_from_plain_text(source, title=title)
        await self._publish_rich_document(
            chat_id, document, cover_prompt,
            correlation_id=correlation_id, ctx=ctx)

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

    async def _plain_fallback(self, chat_id: int, document, *,
                              correlation_id: str | None = None,
                              ctx=None, reason: str = "rich_error") -> None:
        """Даунгрейд rich → plain (Сценарий Б) и §105-доставка (единое ядро).

        Review iter1 (Medium-2): решение о даунгрейде — по ФАКТИЧЕСКОМУ
        содержимому (``looks_rich``), а не по ``response_mode``: rich-разметка
        могла появиться и в ``serious``/``casual`` (нарушение R11 моделью), и
        тогда она обязана быть снята на plain-канале. Принимает §99-документ
        (ON/новый OFF-путь) либо legacy-текст (совместимость)."""
        if isinstance(document, dict):
            doc = document
        else:
            source = (downgrade_rich_to_plain(document)
                      if looks_rich(document) else document)
            from services.summary_article_formatter import (
                document_from_plain_text,
            )
            doc = document_from_plain_text(str(source or ""))
        await self._publish_plain_document(
            chat_id, doc, correlation_id=correlation_id, ctx=ctx,
            reason=reason)

    async def _send_streaming(self, chat_id: int, text: str) -> None:
        """Epic 60 (65.6, T-474): стриминг ТОЛЬКО саммари — placeholder «…» →
        инкрементальные edit_text с накоплением. Темп: приват 1.0с / группа
        3.0с (get_chat; не узнали тип — консервативный групповой).
        «message is not modified» = success; retry_after → сон + РОВНО 1
        повтор, затем drop чанка (финальный edit гарантирует полноту);
        «message is too long» → break в финал/остаток; прочая ошибка edit →
        деградация в _send_chunked. Остаток >4096 — НОВЫМИ сообщениями без
        дублей (сумма без потерь)."""
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
                    return await self._send_chunked(chat_id, text)
            await asyncio.sleep(interval)
        try:                                # финальный edit — полнота (без «…»)
            if acc[:4096] != last_text.rstrip("…"):
                await edit_text_safe(sent, acc[:4096])
        except Exception:
            logger.warning("summary: streaming final edit failed | chat_id=%s",
                           chat_id)
        if len(text) > 4096:                # остаток — НОВЫМИ сообщениями (без дублей)
            await self._send_chunked(chat_id, text[4096:])
        logger.info("summary: streaming done | chat_id=%s", chat_id)

    async def _send_chunked(self, chat_id: int, text: str) -> None:
        chunks = self._chunk_by_whitespace(text, 4096)
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
