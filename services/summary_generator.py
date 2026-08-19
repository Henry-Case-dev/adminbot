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

from aiogram.exceptions import TelegramRetryAfter

from config.settings import settings
from services.database import row_get
from services.llm_client import LLMError
from services.summary_cleanup import cleanup_llm_text
from services.summary_memory import _build_batch_text, fire_and_forget
from services.summary_prompts import SYSTEM_PROMPT
from services.summary_xml import escape_xml_text

try:
    import aiosqlite
    _SQLITE_ERRORS = (sqlite3.Error, aiosqlite.Error)
except ImportError:  # pragma: no cover
    _SQLITE_ERRORS = (sqlite3.Error,)

logger = logging.getLogger(__name__)

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

    async def generate_and_send(self, chat_id: int, manual: bool = False) -> None:
        """Entrypoint for /summary (manual=True) and cron (manual=False). B2/B5."""
        if self._lock.locked():
            if manual:
                await self._send_ux(chat_id, _UX_BUSY)          # B5: не стоять молча
            logger.info(
                "summary: lock busy — queued | chat_id=%s manual=%s", chat_id, manual
            )
        async with self._lock:
            await self._run(chat_id, manual)

    async def _run(self, chat_id: int, manual: bool) -> None:
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
                chat_id, keywords, settings.SUMMARY_RAG_L2_LIMIT
            )
            l2_quotes = [
                self._format_l2_quote(row)
                for row in l2_rows
                if row["text"]
            ]
            l3_facts = await self.memory.vector_search(
                chat_id, " ".join(keywords), settings.SUMMARY_RAG_L3_LIMIT
            )
            try:
                graph_facts = await self.memory.get_graph_facts(chat_id, rows, keywords)
            except Exception:
                logger.warning(
                    "summary: graph facts lookup failed — summary without graph section | chat_id=%s",
                    chat_id, exc_info=True,
                )
                graph_facts = []
            if settings.GRAPH_RAG_ENABLED:
                fire_and_forget(
                    self.memory.memorize_facts(
                        chat_id, _build_batch_text(rows, skip_empty=True), "chat_history"),
                    "summary")
            rag_context = await self.memory.get_rag_context(chat_id, " ".join(keywords))
            user_content = self._compose_user_content(
                xml_context, l2_quotes, l3_facts, graph_facts, rag_context=rag_context
            )
            max_symbols = settings.MAX_SUMMARY_PARTS * 4000 - 200
            # NOTE: {username} must stay literal in the prompt (R11), so we
            # substitute only {max_symbols} via replace, not str.format.
            system = SYSTEM_PROMPT.replace("{max_symbols}", str(max_symbols))
            started = time.monotonic()
            raw = await self.llm.generate(
                [
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ]
            )
            latency_ms = (time.monotonic() - started) * 1000.0
            logger.info(
                "summary LLM raw response | chat_id=%s | len=%d | latency_ms=%.0f | raw=%r",
                chat_id, len(raw), latency_ms, raw,
            )
            raw = cleanup_llm_text(raw)                   # Epic 28 (R28-3)
            text = self._ensure_shiz_postfix(raw, rows)
            await self._send_chunked(chat_id, text)
        except LLMError:
            logger.exception("summary: LLM failed | chat_id=%s", chat_id)
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
                await asyncio.sleep(settings.SUMMARY_CHUNK_DELAY)
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
