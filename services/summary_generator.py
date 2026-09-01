"""Epic 24/25 — SummaryGenerator: full summary pipeline (Sections 33.7 + 34.3).

L3 compress → L1 window → XML → L2 RAG → L3 vectors → LLM → postprocessing
(shiz postfix, 4096-chunking with TelegramRetryAfter handling) → send.

Epic 25 (B2/B4/B5): `generate_and_send(chat_id, manual=False)` — manual calls
(/summary) get UX replies for empty window and busy lock; cron stays quiet
(no ack, no empty-window UX, INFO logs instead). Error UX (R13) is sent to both.
"""
import asyncio
import logging
import re
import sqlite3
import time

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter

from config.settings import settings
from services import hot_config as hot
from services.database import row_get
from services.llm_client import LLMBadResponseError, LLMError
from services.summary_cleanup import cleanup_llm_text
from services.summary_memory import _build_batch_text, fire_and_forget
from services.summary_prompts import SYSTEM_PROMPT
from services.summary_xml import escape_xml_text
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
    """Runs the whole summary pipeline; serialized by a shared asyncio.Lock (A5)."""

    def __init__(self, memory, xml, llm, bot, aliases=None) -> None:
        self.memory = memory
        self.xml = xml
        self.llm = llm
        self.bot = bot
        self.aliases = aliases
        self._lock = asyncio.Lock()

    async def generate_and_send(self, chat_id: int, manual: bool = False,
                                focus: str | None = None) -> None:
        """Entrypoint for /summary (manual=True) and cron (manual=False). B2/B5.
        Epic 65: focus — тема из «/summary про X» (None = обычное саммари)."""
        if self._lock.locked():
            if manual:
                await self._send_ux(chat_id, _UX_BUSY)          # B5: не стоять молча
            logger.info(
                "summary: lock busy — queued | chat_id=%s manual=%s", chat_id, manual
            )
        async with self._lock:
            await self._run(chat_id, manual, focus)

    async def _run(self, chat_id: int, manual: bool, focus: str | None = None) -> None:
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
            xml_context = self.xml.build(rows, self.aliases)
            keywords = self._extract_keywords(rows)
            l2_rows = await self.memory.search_long_term(
                chat_id, keywords, hot.get("limits.summary_rag_l2_limit", settings.SUMMARY_RAG_L2_LIMIT)
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
            rag_context = await self.memory.get_rag_context(chat_id, " ".join(keywords))
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
                hot.get("limits.summary_max_context_tokens", settings.SUMMARY_MAX_CONTEXT_TOKENS), 30000,
                "SUMMARY_MAX_CONTEXT_CHARS", hot.get("limits.summary_max_context_chars", settings.SUMMARY_MAX_CONTEXT_CHARS),
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
            started = time.monotonic()
            payload = [
                {"role": "system", "content": system},
                {"role": "user", "content": user_content},
            ]
            # Epic 60 (65.7, T-475): «печатает…» вокруг LLM-точки (manual И
            # cron — в чат всё равно пишется). Без искусственной паузы.
            # Epic 60 (65.1, T-469): LLMBadResponseError (пустой ответ) —
            # молчание ДО retry-once; R13-ветки не тронуты.
            try:
                async with typing_active(self.bot, chat_id):
                    raw = await self.llm.generate(payload)
            except LLMBadResponseError as exc:
                logger.warning(
                    "summary: empty answer — silence | chat_id=%s | error=%s",
                    chat_id, exc)
                return                     # молчание: ни заглушки, ни реакции
            except LLMError as exc:
                # Epic 47 (D189, 56.6): A — retry-once (пауза SUMMARY_RETRY_ONCE_PAUSE)
                logger.warning("summary: LLM failed — retry-once | chat_id=%s", chat_id)
                await asyncio.sleep(hot.get("limits.summary_retry_once_pause", settings.SUMMARY_RETRY_ONCE_PAUSE))
                try:
                    started = time.monotonic()   # latency_ms — только повторная попытка
                    async with typing_active(self.bot, chat_id):
                        raw = await self.llm.generate(payload)
                except LLMBadResponseError as exc:
                    # 65.1: пустой ответ на повторе — тоже молчание.
                    logger.warning(
                        "summary: empty answer — silence | chat_id=%s | error=%s",
                        chat_id, exc)
                    return
                except LLMError:
                    raise                       # C — UX R13 через внешний except
            latency_ms = (time.monotonic() - started) * 1000.0
            logger.info(
                "summary LLM raw response | chat_id=%s | len=%d | latency_ms=%.0f | raw=%r",
                chat_id, len(raw), latency_ms, raw,
            )
            raw = cleanup_llm_text(raw)                   # Epic 28 (R28-3)
            if not raw.strip():
                # Epic 60 (65.1): после cleanup пусто → молчание (без реакции:
                # message_id в manual-ветку не передаётся — 65.1).
                logger.warning(
                    "summary: empty answer after cleanup — silence | chat_id=%s",
                    chat_id)
                return
            text = self._ensure_shiz_postfix(raw, rows)
            if hot.get("flags.summary_streaming_enabled",
                       settings.SUMMARY_STREAMING_ENABLED):
                await self._send_streaming(chat_id, text)   # Epic 60 (65.6, T-474)
            else:
                await self._send_chunked(chat_id, text)
        except LLMError as exc:
            logger.warning("summary: LLM failed | chat_id=%s | error=%s", chat_id, exc)
            await self._send_ux(chat_id, _UX_LLM_FAILED)
        except _SQLITE_ERRORS:
            logger.exception("summary: DB failed | chat_id=%s", chat_id)
            await self._send_ux(chat_id, _UX_DB_FAILED)
        except Exception:
            logger.exception("summary: unexpected failure | chat_id=%s", chat_id)
            await self._send_ux(chat_id, _UX_GENERIC_FAILED)

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
        parts = []
        if rag_context:                       # Epic 46 (55.5): RAG-контекст ПЕРВЫМ
            parts.append(rag_context)
        if graph_facts:                        # Q8: секция ПЕРВАЯ, до <chat_history>
            escaped = [escape_xml_text(line) for line in graph_facts]
            parts.append(
                "<historical_graph_facts>\n" + "\n".join(escaped) + "\n</historical_graph_facts>"
            )
        parts.append(xml_context)
        if l2_quotes:
            escaped = [escape_xml_text(line) for line in l2_quotes]
            parts.append("<memory>\n" + "\n".join(escaped) + "\n</memory>")
        if l3_facts:
            escaped = [escape_xml_text(line) for line in l3_facts]
            parts.append("<facts>\n" + "\n".join(escaped) + "\n</facts>")
        return "\n\n".join(parts)

    # ── Sending ───────────────────────────────────────────────

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
        sent = await self.bot.send_message(chat_id, "…")
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
                await sent.edit_text(new_text)
                last_text = new_text
            except TelegramRetryAfter as exc:       # сон + РОВНО 1 повтор, затем drop
                await asyncio.sleep(exc.retry_after)
                try:
                    await sent.edit_text(new_text)
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
                await sent.edit_text(acc[:4096])
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
            await self.bot.send_message(chat_id, chunk)
        except TelegramRetryAfter as exc:
            logger.warning(
                "summary: TelegramRetryAfter %.1fs — sleeping, one retry | chat_id=%s",
                exc.retry_after, chat_id,
            )
            await asyncio.sleep(exc.retry_after)
            await self.bot.send_message(chat_id, chunk)

    async def _send_ux(self, chat_id: int, text: str) -> None:
        """Send a UX phrase; its own failure must never crash the run."""
        try:
            await self.bot.send_message(chat_id, text)
        except Exception:
            logger.exception("summary: failed to send UX message | chat_id=%s", chat_id)
