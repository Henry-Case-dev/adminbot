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
from services.database import row_get
from services.summary_prompts import COMPRESS_PROMPT, EXTRACT_PROMPT

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)

_VEC_TABLE_SQL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS smart_archive USING vec0("
    "embedding float[{dim}] distance_metric=cosine, +fact_id INTEGER, +chat_id INTEGER)"
)

# ── GraphRAG (Epic 26, Section 35) ──────────────────────────────

_GRAPH_EXTRACT_MAX_CHARS = 8000      # tail of the batch text sent to extraction (Q5)
_GRAPH_MAX_NAME_CHARS = 100          # cap for subject/object entity names (35.4)
_GRAPH_MAX_RELATION_CHARS = 200      # cap for the predicate (35.4)


class GraphExtractionError(Exception):
    """Raw LLM extraction answer is not a JSON array of triplets (35.4)."""


def _normalize_name(s: str) -> str:
    """D70: strip + collapse repeated whitespace + lower (shared by extract and lookup)."""
    return re.sub(r"\s+", " ", str(s)).strip().lower()


def parse_triplets(raw: str) -> list[dict]:
    """Parse a raw LLM answer into valid triplets (35.4).

    Accepts a JSON array, a JSON object holding a list value, and a code-fenced
    payload. Invalid items inside a valid array are skipped (aggregated WARNING);
    an invalid structure raises GraphExtractionError.
    """
    text = str(raw).strip()
    candidates = [text]
    if text.startswith("```"):
        unwrapped = re.sub(r"^```[a-zA-Z]*\s*", "", text)
        unwrapped = re.sub(r"\s*```\s*$", "", unwrapped)
        if unwrapped != text:
            candidates.append(unwrapped)
    data = None
    for candidate in candidates:
        try:
            data = json.loads(candidate)
            break
        except (ValueError, TypeError):
            continue
    if isinstance(data, dict):
        for value in data.values():
            if isinstance(value, list):
                data = value
                break
        else:
            data = None
    if not isinstance(data, list):
        raise GraphExtractionError("extraction answer is not a JSON array of triplets")

    triplets = []
    skipped = 0
    for item in data:
        triplet = _validate_triplet(item)
        if triplet is None:
            skipped += 1
            continue
        triplets.append(triplet)
        if len(triplets) >= settings.GRAPH_EXTRACT_MAX_TRIPLETS:
            break
    if skipped:
        logger.warning("graph extract: skipped %d invalid triplets", skipped)
    return triplets


def _validate_triplet(item) -> dict | None:
    """Return a normalized valid triplet dict or None when the item must be skipped."""
    if not isinstance(item, dict):
        return None
    try:
        subject = item["subject"]
        subject_type = item["subject_type"]
        predicate = item["predicate"]
        obj = item["object"]
        object_type = item["object_type"]
    except (KeyError, TypeError):
        return None
    if not all(
        isinstance(value, str)
        for value in (subject, subject_type, predicate, obj, object_type)
    ):
        return None
    if subject_type not in ("user", "topic") or object_type not in ("user", "topic"):
        return None
    norm_subject = _normalize_name(subject)
    norm_predicate = _normalize_name(predicate)
    norm_obj = _normalize_name(obj)
    if not norm_subject or not norm_predicate or not norm_obj:
        return None
    if len(norm_subject) > _GRAPH_MAX_NAME_CHARS or len(norm_obj) > _GRAPH_MAX_NAME_CHARS:
        return None
    if len(norm_predicate) > _GRAPH_MAX_RELATION_CHARS:
        return None
    if norm_subject == norm_obj:
        return None
    return {
        "subject": norm_subject,
        "subject_type": subject_type,
        "predicate": norm_predicate,
        "object": norm_obj,
        "object_type": object_type,
    }


def _build_batch_text(batch: list, skip_empty: bool = False) -> str:
    """Same '[author]: text' lines as the compress prompt (DRY, 35.4).

    Epic 28 (R28-1): rows with is_forward get the source marker:
    [Оля (репост из "Канал X")]: текст / [Оля (репост)]: текст.
    """
    lines = []
    for row in batch:
        author = (row["author_name"] or "").strip() or "unknown"
        text = row["text"] or ""
        if skip_empty and not text:
            continue
        if row_get(row, "is_forward"):
            source = (row_get(row, "forward_source") or "").replace('"', "'").strip()
            author = f'{author} (репост из "{source}")' if source else f"{author} (репост)"
        lines.append(f"[{author}]: {text}")
    return "\n".join(lines)


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
        self._vec_dim = None

    # ── Initialization (R3: graceful sqlite-vec load + self-heal) ──────────

    async def initialize(self) -> bool:
        """Load sqlite-vec + self-heal dimension mismatch (Epic 28, R28-2). Never raises."""
        self._vec_available = False
        self._vec_dim = None
        try:
            import sqlite_vec

            await self.db.db.enable_load_extension(True)
            await self.db.db.load_extension(sqlite_vec.loadable_path())
            actual_dim = None
            try:
                vectors = await self.llm.embed(["probe"])
                if vectors and vectors[0]:
                    actual_dim = len(vectors[0])
            except Exception:
                logger.warning("SmartModule: probe embed failed — FTS5 fallback", exc_info=True)
            if actual_dim is None:
                return False
            if actual_dim != int(settings.EMBEDDING_DIM):
                logger.warning(
                    "SmartModule: EMBEDDING_DIM=%s != actual API dim=%d — using actual",
                    settings.EMBEDDING_DIM, actual_dim,
                )
            stored_dim = None
            cursor = await self.db.db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name='smart_archive'"
            )
            row = await cursor.fetchone()
            if row and row["sql"]:
                match = re.search(r"float\[(\d+)\]", row["sql"])
                if match:
                    stored_dim = int(match.group(1))
                else:
                    logger.warning(
                        "SmartModule: could not parse stored dim from smart_archive DDL — "
                        "runtime guard active (no dimension self-heal)"
                    )
            if stored_dim is not None and stored_dim != actual_dim:
                logger.warning(
                    "SmartModule: vec dimension mismatch (stored=%d, actual=%d) — "
                    "dropping smart_archive (facts in smart_archive_facts are kept)",
                    stored_dim, actual_dim,
                )
                await self.db.db.execute("DROP TABLE smart_archive")
            await self.db.db.execute(_VEC_TABLE_SQL.format(dim=actual_dim))
            await self.db.db.commit()
            self._vec_dim = actual_dim
            self._vec_available = True
            logger.info("SmartModule: sqlite-vec loaded (dim=%d)", actual_dim)
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
                    if facts:
                        logger.info(
                            "SmartModule L3: knn_hits=%d | chat_id=%s", len(facts), chat_id
                        )
                        return facts
                    logger.info(
                        "SmartModule L3: KNN empty — FTS5 fallback | chat_id=%s", chat_id
                    )
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

    # ── GraphRAG lookup for /summary (R26-3, D71) ───────────────

    async def get_graph_facts(
        self, chat_id: int, rows: list, keywords: list[str]
    ) -> list[str]:
        """R26-3: детерминированный graph-поиск по сущностям окна L1 → строки справок."""
        if not settings.GRAPH_RAG_ENABLED:
            return []
        try:
            user_names = [
                _normalize_name(r["author_name"])
                for r in rows
                if (r["author_name"] or "").strip()
            ]
            topic_kws = [kw.lower() for kw in keywords[:2]]
            entity_ids = await self.db.match_nodes(chat_id, user_names, topic_kws)
            if entity_ids:
                edges = await self.db.get_top_edges(
                    chat_id, entity_ids, settings.GRAPH_TOP_EDGES_LIMIT
                )
                if not edges:                       # сущности есть, но рёбер у них нет
                    edges = await self.db.get_top_edges_all(
                        chat_id, settings.GRAPH_TOP_EDGES_LIMIT
                    )
            else:                                   # окно не сматчилось ни с одним узлом (холодный граф)
                edges = await self.db.get_top_edges_all(
                    chat_id, settings.GRAPH_TOP_EDGES_LIMIT
                )
            facts = [self._format_graph_fact(e) for e in edges]
            logger.info("SmartModule graph: facts=%d | chat_id=%s", len(facts), chat_id)
            return facts
        except Exception:
            logger.warning(
                "SmartModule graph: lookup failed — summary without graph section | chat_id=%s",
                chat_id,
                exc_info=True,
            )
            return []

    @staticmethod
    def _format_graph_fact(row) -> str:
        """One line per edge: [Историческая справка: A (relation) B] (35.5)."""
        return (
            f"[Историческая справка: {row['source_name']} "
            f"({row['relation_type']}) {row['target_name']}]"
        )

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
                if settings.GRAPH_RAG_ENABLED:                       # D69: False → ровно старое поведение
                    await self._extract_and_save_graph(chat_id, batch)  # LLM-вызов №2 + nodes/edges (D68)
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
        user_content = _build_batch_text(batch, skip_empty=False)
        raw = await self.llm.generate(
            [
                {"role": "system", "content": COMPRESS_PROMPT},
                {"role": "user", "content": user_content},
            ]
        )
        facts = [line.strip() for line in raw.splitlines() if line.strip()]
        return facts[:10]

    async def _extract_and_save_graph(self, chat_id: int, batch: list) -> None:
        """R26-2: one extra LLM call per batch → nodes/edges upsert (35.4).

        Raises on any failure (LLM / parsing / DB) — the caller keeps the batch.
        """
        text = _build_batch_text(batch, skip_empty=True)
        if not text:
            logger.info(
                "graph extract: batch has no captions — nothing to extract | chat_id=%s",
                chat_id,
            )
            return
        tail = text[-_GRAPH_EXTRACT_MAX_CHARS:]
        raw = await self.llm.generate(
            [
                {"role": "system", "content": EXTRACT_PROMPT},
                {"role": "user", "content": tail},
            ]
        )
        triplets = parse_triplets(raw)
        for triplet in triplets:
            sid = await self.db.upsert_node(
                chat_id, _normalize_name(triplet["subject"]), triplet["subject_type"]
            )
            oid = await self.db.upsert_node(
                chat_id, _normalize_name(triplet["object"]), triplet["object_type"]
            )
            await self.db.upsert_edge(
                sid,
                oid,
                _normalize_name(triplet["predicate"]),
                weight_increment=settings.GRAPH_EDGE_WEIGHT_INCREMENT,
            )
        logger.info("graph: triplets=%d | chat_id=%s", len(triplets), chat_id)

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
        except Exception as exc:
            message = str(exc).lower()
            if "dimension" in message or "mismatch" in message:
                self._vec_available = False
                logger.error(
                    "SmartModule L3: dimension mismatch on INSERT — vec disabled until "
                    "restart (self-heal on next start) | fact_id=%d",
                    fact_id, exc_info=True,
                )
            else:
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
