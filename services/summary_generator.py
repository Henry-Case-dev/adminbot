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
from services.llm_client import LLMBadResponseError, LLMError
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
from services.system2_handoff import parse_summary_handoff
from services.external_log import log_external_api
from services.image_generation import generate_image_verbose
from services.smartmodule_concurrency import get_smartmodule_concurrency_pool
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
    """

    text: str
    cover_prompt: str = ""
    # F6 (10.24, ADR-1024-10 D3): ``""`` = режим не выбран (сбойный путь) —
    # fallback-ключ резолвится в compose, без второго источника дефолта.
    response_mode: str = ""


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
        correlation_id = usage_events.new_correlation_id()
        try:
            await self.memory.compress_and_purge(chat_id)
            rows = await self.memory.get_window_messages(chat_id)
            if not rows:
                if manual:
                    await self._send_ux(chat_id, _UX_EMPTY)     # B4
                logger.info(
                    "summary: empty window | chat_id=%s manual=%s — no LLM call",
                    chat_id, manual,
                )
                return
            xml_context = self.xml.build(rows, self.aliases, trigger_message_id)
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
                            settings.SUMMARY_MAX_CONTEXT_TOKENS)), 30000,
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
                return
            raw = cleanup_llm_text(raw)                   # Epic 28 (R28-3)
            raw = _strip_safe_html(raw)                   # review iter1 (H2)
            if not raw.strip():
                # Epic 60 (65.1): после cleanup пусто → молчание (без реакции:
                # message_id в manual-ветку не передаётся — 65.1).
                logger.warning(
                    "summary: empty answer after cleanup — silence | chat_id=%s",
                    chat_id)
                return
            text = self._ensure_shiz_postfix(raw, rows)
            cover_prompt = draft.cover_prompt if draft is not None else ""
            # F6 (ADR-1023-6 §3.4): Article-ветка — только если флаг ON,
            # обложка возможна и aiogram поддерживает media. Иначе — прежний
            # plain-путь байт-в-байт (R11).
            if (cover_prompt
                    and getattr(settings, "SUMMARY_COVER_ARTICLE_ENABLED", True)
                    and _rich_media_supported()):
                await self._deliver_rich(chat_id, text, cover_prompt,
                                         correlation_id=correlation_id)
            else:
                await self._deliver_plain(chat_id, text)
        except LLMError as exc:
            logger.warning("summary: LLM failed | chat_id=%s | error=%s", chat_id, exc)
            await self._send_ux(chat_id, _UX_LLM_FAILED)
        except _SQLITE_ERRORS:
            logger.exception("summary: DB failed | chat_id=%s", chat_id)
            await self._send_ux(chat_id, _UX_DB_FAILED)
        except Exception:
            logger.exception("summary: unexpected failure | chat_id=%s", chat_id)
            await self._send_ux(chat_id, _UX_GENERIC_FAILED)

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
        editor_raw = await self._llm_generate(
            editor_payload, chat_id, correlation_id=correlation_id,
            step="stage1")
        if editor_raw is None:
            return None
        parsed = parse_summary_handoff(editor_raw)
        if parsed is None:
            logger.info(
                "summary system2: невалидная выжимка редактора — fallback | "
                "chat_id=%s", chat_id)
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
        return SummaryDraft(text=text, cover_prompt=cover_prompt,
                            response_mode=response_mode)

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

    async def _deliver_plain(self, chat_id: int, text: str) -> None:
        """Прежний plain-путь (стриминг/чанки) — R11, ``parse_mode=None``."""
        if hot.get("flags.summary_streaming_enabled",
                   settings.SUMMARY_STREAMING_ENABLED):
            await self._send_streaming(chat_id, text)   # Epic 60 (65.6, T-474)
        else:
            await self._send_chunked(chat_id, text)

    async def _deliver_rich(self, chat_id: int, text: str,
                            cover_prompt: str,
                            correlation_id: str | None = None) -> None:
        """F6 (ADR-1023-6 §3.4): обложка (F5) → Article (`sendRichMessage`).

        Тихий фолбэк (D8): любая ошибка генерации/отправки → plain-путь без
        сообщений пользователю; лог — только класс ошибки (R17). Rich-ветка не
        стримит → дублей нет. F7 rework: ``correlation_id`` саммари едет в
        генерацию обложки — событие ``step='image'`` остаётся в дереве."""
        tmp_path = None
        try:
            style = hot.get("prompts.summary_cover_style",
                            SUMMARY_COVER_STYLE_DEFAULT)
            image_prompt = compose_cover_image_prompt(style, cover_prompt)
            # F12/ADR-1024-4 D2 (UPD2 п.10.1): доказательство подмешивания
            # стиля — R17-safe, без полного текста промпта (только длины).
            style_text = (style or "").strip()
            visual_text = (cover_prompt or "").strip()
            logger.info(
                "summary cover: prompt composed | style_present=%s | "
                "style_len=%d | visual_len=%d | final_len=%d | chat_id=%s",
                bool(style_text), len(style_text), len(visual_text),
                len(image_prompt), chat_id)
            tmp_path, img_reason = await generate_image_verbose(
                image_prompt, chat_id=chat_id,
                correlation_id=correlation_id)
            if not tmp_path:
                # F12/ADR-1024-4 D4: «тихий откат» для юзера ≠ тишина в логах —
                # реальная причина (уже R17-safe код из image-слоя).
                logger.info(
                    "summary cover: image unavailable (%s) — plain fallback | "
                    "chat_id=%s", img_reason, chat_id)
                log_external_api(
                    logger, provider="image", method="post", status=None,
                    reason=img_reason, level=logging.ERROR)
                return await self._plain_fallback(chat_id, text)
            media = [build_cover_media(tmp_path)]
            await self._send_rich_with_retry(chat_id, text, media)
            logger.info("summary cover: article sent | chat_id=%s", chat_id)
        except Exception as exc:
            logger.warning(
                "summary cover: rich fallback | chat_id=%s | error=%s",
                chat_id, type(exc).__name__)
            return await self._plain_fallback(chat_id, text)
        finally:
            if tmp_path:
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    async def _send_rich_with_retry(self, chat_id: int, text: str,
                                    media: list) -> None:
        """Article ровно 1 повтор по ``retry_after``, затем исключение → plain."""
        try:
            await send_rich_message(
                self.bot, chat_id, text, media=media,
                cover_id=SUMMARY_COVER_MEDIA_ID)
        except TelegramRetryAfter as exc:
            logger.warning(
                "summary cover: TelegramRetryAfter %.1fs — one retry | "
                "chat_id=%s", exc.retry_after, chat_id)
            await asyncio.sleep(exc.retry_after)
            await send_rich_message(
                self.bot, chat_id, text, media=media,
                cover_id=SUMMARY_COVER_MEDIA_ID)

    async def _plain_fallback(self, chat_id: int, text: str) -> None:
        """Даунгрейд rich → plain (Сценарий Б) и прежняя доставка.

        Review iter1 (Medium-2): решение о даунгрейде — по ФАКТИЧЕСКОМУ
        содержимому (``looks_rich``), а не по ``response_mode``: rich-разметка
        могла появиться и в ``serious``/``casual`` (нарушение R11 моделью), и
        тогда она обязана быть снята на plain-канале."""
        plain_text = downgrade_rich_to_plain(text) if looks_rich(text) else text
        await self._deliver_plain(chat_id, plain_text)

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
