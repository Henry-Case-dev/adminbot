"""Epic 24 — three-level chat memory manager (R2/R3, Section 33.5).

L1: generation window (SUMMARY_WINDOW_HOURS), one SQL pass.
L2: raw messages for FTS5-RAG (FULL_MEMORY_RETENTION_DAYS).
L3: compressed archive facts + sqlite-vec KNN with mandatory FTS5 fallback.
"""
import json
import logging
import re
import time

from config.settings import settings
from services.summary_prompts import COMPRESS_PROMPT

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)

_VEC_TABLE_SQL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS smart_archive USING vec0("
    "embedding float[{dim}] distance_metric=cosine, +fact_id INTEGER, +chat_id INTEGER)"
)


def build_fts_query(keywords: list[str]) -> str:
    """Sanitize keywords and build an FTS5 prefix query: "kw1"* OR "kw2"* …

    User-provided `"` and `*` are stripped (RESEARCH §f — они ломают парсер),
    the trailing `*` we add ourselves enables Russian prefix matching
    (unicode61 has no stemming).
    """
    cleaned = []
    for keyword in keywords:
        kw = str(keyword).replace('"', "").replace("*", "").strip()
        if kw:
            cleaned.append(f'"{kw}"*')
    return " OR ".join(cleaned)


class MemoryManager:
    """Owns L1/L2 access and the L3 archive (text + optional vec0)."""

    def __init__(self, db, llm) -> None:
        self.db = db
        self.llm = llm
        self._vec_available = False

    # ── Initialization (R3: graceful sqlite-vec load) ──────────

    async def initialize(self) -> bool:
        """Try to load sqlite-vec and create the vec0 table. Never raises."""
        self._vec_available = False
        try:
            import sqlite_vec

            await self.db.db.enable_load_extension(True)
            await self.db.db.load_extension(sqlite_vec.loadable_path())
            dim = int(settings.EMBEDDING_DIM)
            await self.db.db.execute(_VEC_TABLE_SQL.format(dim=dim))
            await self.db.db.commit()
            self._vec_available = True
            logger.info("SmartModule: sqlite-vec loaded (dim=%d)", dim)
        except Exception:
            logger.warning(
                "SmartModule: sqlite-vec unavailable — FTS5 fallback (R3)",
                exc_info=True,
            )
        finally:
            try:
                await self.db.db.enable_load_extension(False)
            except Exception:
                pass
        return self._vec_available

    @property
    def vec_available(self) -> bool:
        return self._vec_available

    # ── L1 window ──────────────────────────────────────────────

    async def get_window_messages(self, chat_id: int) -> list:
        """L1: messages within SUMMARY_WINDOW_HOURS, one SQL pass."""
        since = int(time.time()) - int(settings.SUMMARY_WINDOW_HOURS * 3600)
        rows = await self.db.get_smart_window(
            chat_id, since, settings.SUMMARY_MAX_WINDOW_MESSAGES
        )
        logger.info(
            "SmartModule L1: window_size=%d | chat_id=%s | since_ts=%d",
            len(rows), chat_id, since,
        )
        return rows

    # ── L2 RAG (FTS5, no extra LLM call — A7) ──────────────────

    async def search_long_term(self, chat_id: int, keywords: list[str], limit: int) -> list:
        query = build_fts_query(keywords)
        if not query:
            logger.info("SmartModule L2: no keywords — skipping RAG | chat_id=%s", chat_id)
            return []
        rows = await self.db.search_messages_fts(chat_id, query, limit)
        logger.info(
            "SmartModule L2: rag_hits=%d | chat_id=%s | query_len=%d",
            len(rows), chat_id, len(query),
        )
        return rows

    # ── L3 vector search (vec0 KNN → FTS5 fallback, R3/D60) ────

    async def vector_search(self, chat_id: int, query: str, limit: int) -> list[str]:
        if self._vec_available:
            try:
                vectors = await self.llm.embed([query])
                if vectors and vectors[0]:
                    facts = await self._search_archive_knn(chat_id, vectors[0], limit)
                    logger.info(
                        "SmartModule L3: knn_hits=%d | chat_id=%s", len(facts), chat_id
                    )
                    return facts
            except Exception:
                logger.warning(
                    "SmartModule L3: vector search failed — FTS5 fallback | chat_id=%s",
                    chat_id, exc_info=True,
                )
        facts = await self._fts_search_archive(chat_id, query, limit)
        logger.info(
            "SmartModule L3: fts_hits=%d | chat_id=%s (fallback=%s)",
            len(facts), chat_id, not self._vec_available,
        )
        return facts

    async def _search_archive_knn(self, chat_id: int, vector: list[float], limit: int) -> list[str]:
        # vec0 (0.1.x) не поддерживает JOIN внутри KNN-запроса — поэтому
        # KNN top-k выполняется отдельно, фильтр chat_id и выборка фактов — в Python.
        embedding_json = json.dumps(vector)
        cursor = await self.db.db.execute(
            "SELECT fact_id, chat_id, distance FROM smart_archive "
            "WHERE embedding MATCH ? AND k = ?",
            (embedding_json, limit),
        )
        rows = await cursor.fetchall()
        fact_ids = [row["fact_id"] for row in rows if row["chat_id"] == chat_id][:limit]
        if not fact_ids:
            return []
        placeholders = ",".join("?" for _ in fact_ids)
        cursor = await self.db.db.execute(
            f"SELECT id, fact FROM smart_archive_facts WHERE id IN ({placeholders})",
            fact_ids,
        )
        by_id = {row["id"]: row["fact"] for row in await cursor.fetchall()}
        return [by_id[fid] for fid in fact_ids if fid in by_id]

    async def _fts_search_archive(self, chat_id: int, query: str, limit: int) -> list[str]:
        keywords = _TOKEN_RE.findall(str(query).lower())
        match_query = build_fts_query(keywords)
        if not match_query:
            return []
        return await self.db.search_archive_fts(chat_id, match_query, limit)

    # ── L3 compression + retention (A5: called only under generator lock) ──

    async def compress_and_purge(self, chat_id: int) -> None:
        cutoff = int(time.time()) - settings.FULL_MEMORY_RETENTION_DAYS * 86400
        batch_size = settings.SUMMARY_COMPRESS_BATCH
        processed = 0
        while True:
            batch = await self.db.get_smart_raw(chat_id, cutoff, batch_size)
            if not batch:
                break
            ids = [row["id"] for row in batch]
            try:
                facts = await self._compress_batch(batch)
                if not facts:
                    logger.warning(
                        "SmartModule L3: compress returned no facts — batch kept | chat_id=%s",
                        chat_id,
                    )
                    break
                now = int(time.time())
                for fact in facts:
                    fact_id = await self.db.save_archive_fact(chat_id, fact, now)
                    if self._vec_available:
                        await self._save_archive_embedding(chat_id, fact_id, fact)
            except Exception:
                logger.exception(
                    "SmartModule L3: compress batch failed — raw kept, pipeline continues | chat_id=%s",
                    chat_id,
                )
                break
            # успешная пачка удаляется ПОСЛЕ сохранения фактов (33.5 step 4)
            await self.db.delete_smart_messages_by_ids(chat_id, ids)
            processed += len(ids)
            if len(ids) < batch_size:
                break
        if processed:
            logger.info(
                "SmartModule L3: compressed %d messages | chat_id=%s", processed, chat_id
            )
        await self._purge_archive(chat_id)

    async def _compress_batch(self, batch: list) -> list[str]:
        lines = []
        for row in batch:
            author = (row["author_name"] or "").strip() or "unknown"
            text = row["text"] or ""
            lines.append(f"[{author}]: {text}")
        user_content = "\n".join(lines)
        raw = await self.llm.generate(
            [
                {"role": "system", "content": COMPRESS_PROMPT},
                {"role": "user", "content": user_content},
            ]
        )
        facts = [line.strip() for line in raw.splitlines() if line.strip()]
        return facts[:10]

    async def _save_archive_embedding(self, chat_id: int, fact_id: int, fact: str) -> None:
        try:
            vectors = await self.llm.embed([fact])
            vector = vectors[0]
            await self.db.db.execute(
                "INSERT INTO smart_archive(rowid, fact_id, chat_id, embedding) "
                "VALUES (?, ?, ?, ?)",
                (fact_id, fact_id, chat_id, json.dumps(vector)),
            )
            await self.db.db.commit()
        except Exception:
            logger.warning(
                "SmartModule L3: embed/vec insert failed for fact_id=%d — fact stays in FTS5 only",
                fact_id, exc_info=True,
            )

    async def _purge_archive(self, chat_id: int) -> None:
        archive_cutoff = int(time.time()) - settings.ARCHIVE_MEMORY_RETENTION_DAYS * 86400
        if self._vec_available:
            try:
                # vec0: документированная форма удаления — rowid IN (...).
                # rowid == fact_id по инварианту INSERT в _save_archive_embedding.
                await self.db.db.execute(
                    "DELETE FROM smart_archive WHERE rowid IN "
                    "(SELECT id FROM smart_archive_facts WHERE chat_id = ? AND timestamp < ?)",
                    (chat_id, archive_cutoff),
                )
                await self.db.db.commit()
            except Exception:
                logger.warning(
                    "SmartModule L3: vec purge failed | chat_id=%s", chat_id, exc_info=True
                )
        deleted = await self.db.delete_archive_facts_older_than(chat_id, archive_cutoff)
        if deleted:
            logger.info(
                "SmartModule L3: archive retention purged %d facts | chat_id=%s",
                deleted, chat_id,
            )
