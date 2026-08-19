"""Epic 24 — three-level chat memory manager (R2/R3, Section 33.5).

L1: generation window (SUMMARY_WINDOW_HOURS), one SQL pass.
L2: raw messages for FTS5-RAG (FULL_MEMORY_RETENTION_DAYS).
L3: compressed archive facts + sqlite-vec KNN with mandatory FTS5 fallback.

Epic 46 (Section 55): GraphRAG v2 — memorize_facts (Fact Extractor, канон
R46-2), гибридный RAG (build_rag_context, канон R46-4), fire_and_forget-хуки,
фиксы диагностики 55.8 (_embed-ретраи, vec-реактивация, backfill).
"""
import asyncio
import json
import logging
import re
import time

from config.settings import settings
from services.database import row_get
from services.summary_prompts import COMPRESS_PROMPT, EXTRACT_PROMPT
from services.summary_xml import escape_xml_text

logger = logging.getLogger(__name__)

_TOKEN_RE = re.compile(r"[а-яёa-z0-9]+", re.IGNORECASE)

_VEC_TABLE_SQL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS smart_archive USING vec0("
    "embedding float[{dim}] distance_metric=cosine, +fact_id INTEGER, +chat_id INTEGER)"
)

_GRAPH_VEC_TABLE_SQL = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS graph_facts_vec USING vec0("
    "embedding float[{dim}] distance_metric=cosine, +fact_id INTEGER, "
    "+chat_id INTEGER, +origin TEXT, +expires_at INTEGER)"
)

# ── GraphRAG v2 (Epic 46, Sections 55.4/55.5/55.6/55.8) ───────────

# КАНОН R46-2 — промпт-экстрактор (VERBATIM, байт-в-байт; тест-якорь backlog
# «Канон R46-2 — промпт-экстрактор»).
FACT_EXTRACT_PROMPT = """СИСТЕМНАЯ РОЛЬ:
Ты — безэмоциональный архивариус (ETL-процессор). Твоя задача: извлечь сухие, проверяемые факты из предоставленного текста и представить их в виде графовых триплетов (Субъект -> Предикат -> Объект).
- Игнорируй любые эмоции, шутки, оскорбления и личности авторов запроса.
- Извлекай только объективную информацию (суть статьи, результаты поиска, тезисы видео).
- Если текст содержит техническую или справочную инфу — сохрани её максимально точно.

ВЫВОД:
Верни строго JSON со списком фактов. Пример: [{"subject": "Ozon", "predicate": "доставляет быстрее чем", "object": "Wildberries", "context": "из-за большего количества складов"}]"""

_FACT_ORIGINS = ("chat_history", "search_fact", "youtube_content", "web_content")
_FACT_EXTRACT_MAX_CHARS = 8000      # tail текста, отправляемый экстрактору
_FACT_MAX_NAME_CHARS = 100
_FACT_MAX_PREDICATE_CHARS = 200
_FACT_MAX_CONTEXT_CHARS = 400

_YOUTUBE_MEMORIZE_MAX_CHARS = 8000   # порог «огромных субтитров» (55.5)

_MEMORIZE_COMPRESS_PROMPT = (
    "ты — сжиматель длинного текста. верни сухие факты и тезисы исходного "
    "текста, отдельными строками, без нумерации, маркдауна и смайлов, не "
    "больше 20 строк. токсичность и оценки НЕ добавляй."
)

_EMBED_RETRY_ATTEMPTS = 3            # ретраи на ошибках embed (в т.ч. 403)
_EMBED_RETRY_BACKOFF = 1.0           # сон backoff_base * 2**n
_VEC_REACTIVATE_INTERVAL = 600.0     # re-probe не чаще раза в 10 мин
_BACKFILL_BATCH = 50                 # батч backfill
_BACKFILL_MAX_FACTS = 500            # потолок фактов за один вызов backfill

_RAG_PREFIXES = {
    "search_fact": "[Из твоего прошлого поиска]: ",
    "youtube_content": "[Из видео, которое кидали ранее]: ",
    "web_content": "[Из статьи]: ",
}

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


def parse_fact_list(raw: str) -> list[dict]:
    """Толерантный парсер фактов (55.4): JSON-массив {subject, predicate,
    object, context?} (context опционален). НИКОГДА не бросает: кривой JSON /
    не-массив → [] + WARNING (тихий лог R46-5). Code-fence и объект-со-списком
    принимаются (прецедент parse_triplets 35.4); невалидные элементы
    пропускаются; капсы имён/предиката/контекста; subject == object — мимо."""
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
        logger.warning("graphrag memorize: LLM answer is not a JSON list — skipped")
        return []
    facts = []
    for item in data:
        fact = _validate_fact(item)
        if fact is None:
            continue
        facts.append(fact)
        if len(facts) >= settings.GRAPH_EXTRACT_MAX_TRIPLETS:
            break
    return facts


def _validate_fact(item) -> dict | None:
    if not isinstance(item, dict):
        return None
    try:
        subject, predicate, obj = item["subject"], item["predicate"], item["object"]
    except (KeyError, TypeError):
        return None
    context = item.get("context")
    if not all(isinstance(v, str) for v in (subject, predicate, obj)):
        return None
    if context is not None and not isinstance(context, str):
        context = None
    norm_s, norm_p, norm_o = map(_normalize_name, (subject, predicate, obj))
    if not (norm_s and norm_p and norm_o):
        return None
    if len(norm_s) > _FACT_MAX_NAME_CHARS or len(norm_o) > _FACT_MAX_NAME_CHARS:
        return None
    if len(norm_p) > _FACT_MAX_PREDICATE_CHARS:
        return None
    if norm_s == norm_o:
        return None
    ctx = re.sub(r"\s+", " ", context).strip() if context else ""
    return {"subject": norm_s, "predicate": norm_p, "object": norm_o,
            "context": ctx[:_FACT_MAX_CONTEXT_CHARS]}


def fire_and_forget(coro, tag: str) -> None:
    """R46-3/R46-5: asyncio.create_task + тихий лог. Падение фонового факта
    НЕ всплывает в чат (исключение не теряется — ловится здесь)."""
    async def _run() -> None:
        try:
            await coro
        except Exception:
            logger.warning("[graphrag hook] %s failed", tag, exc_info=True)
    asyncio.create_task(_run())


async def _memorize_youtube(memory, chat_id: int, transcript: str) -> None:
    """<= _YOUTUBE_MEMORIZE_MAX_CHARS → memorize сырых субтитров; иначе —
    сжатая НЕТОКСИЧНАЯ выжимка через _MEMORIZE_COMPRESS_PROMPT (ВНУТРИ фоновой
    задачи — чат не ждёт LLM-сжатия)."""
    text = str(transcript or "")
    if not text.strip():
        return
    if len(text) <= _YOUTUBE_MEMORIZE_MAX_CHARS:
        await memory.memorize_facts(chat_id, text, "youtube_content")
        return
    try:
        raw = await memory.llm.generate([
            {"role": "system", "content": _MEMORIZE_COMPRESS_PROMPT},
            {"role": "user", "content": text[-_FACT_EXTRACT_MAX_CHARS:]},
        ])
        await memory.memorize_facts(chat_id, raw, "youtube_content")
    except Exception:
        logger.warning("[graphrag hook] youtube compress failed", exc_info=True)


def build_rag_context(facts: list) -> str:
    """R46-4 (55.6): КАНОН-структура `<context>/<user_gossip>/<bot_knowledge>`.
    facts: [(origin, fact), ...]. chat_history → user_gossip БЕЗ префикса;
    остальные → bot_knowledge с канон-префиксами (unknown origin — без префикса).
    escape_xml_text ОБЯЗАТЕЛЕН (summary_xml). Пустые факты → "". Формат
    байт-в-байт (два пробела отступа; пустой блок — `<block></block>`)."""
    gossip = [escape_xml_text(fact) for origin, fact in facts
              if origin == "chat_history"]
    knowledge = [
        _RAG_PREFIXES.get(origin, "") + escape_xml_text(fact)
        for origin, fact in facts if origin != "chat_history"
    ]
    if not gossip and not knowledge:
        return ""
    lines = ["<context>",
             "  <user_gossip>" + "\n".join(gossip) + "</user_gossip>",
             "  <bot_knowledge>" + "\n".join(knowledge) + "</bot_knowledge>",
             "</context>"]
    return "\n".join(lines)


class MemoryManager:
    """Owns L1/L2 access and the L3 archive (text + optional vec0).

    Epic 46 (55.8): _vec_off_reason «extension»|«embed», deferred-реактивация
    после embed-фейла (re-probe раз в _VEC_REACTIVATE_INTERVAL), backfill.
    """

    def __init__(self, db, llm) -> None:
        self.db = db
        self.llm = llm
        self._vec_available = False
        self._vec_dim = None
        self._vec_off_reason: str | None = None      # "extension" | "embed"
        self._embed_degraded_at = 0.0
        self._reactivate_lock = asyncio.Lock()

    # ── Initialization (R3: graceful sqlite-vec load + self-heal) ──────────

    async def initialize(self) -> bool:
        """Load sqlite-vec + self-heal dimension mismatch (Epic 28/46,
        R28-2/R46-8). Never raises. Epic 46 (55.8): разделение логов —
        «sqlite-vec unavailable» (extension) vs «probe embed failed» (embed);
        embed-фейл → deferred-состояние (re-probe на следующем поиске)."""
        self._vec_available = False
        self._vec_dim = None
        self._vec_off_reason = None
        try:
            import sqlite_vec
        except Exception:
            self._vec_off_reason = "extension"
            logger.warning(
                "SmartModule: sqlite-vec unavailable — FTS5 fallback (R3)",
                exc_info=True,
            )
            return False
        try:
            await self.db.db.enable_load_extension(True)
            await self.db.db.load_extension(sqlite_vec.loadable_path())
        except Exception:
            self._vec_off_reason = "extension"
            logger.warning(
                "SmartModule: sqlite-vec unavailable — FTS5 fallback (R3)",
                exc_info=True,
            )
            return False
        finally:
            try:
                await self.db.db.enable_load_extension(False)
            except Exception:
                pass
        try:
            actual_dim = None
            try:
                vectors = await self._embed(["probe"])
                if vectors and vectors[0]:
                    actual_dim = len(vectors[0])
            except Exception as exc:
                self._vec_off_reason = "embed"
                self._embed_degraded_at = time.monotonic()
                logger.warning(
                    "SmartModule: probe embed failed (%s) — vec deferred, FTS5 fallback "
                    "(re-probe on next search)", exc,
                )
                return False
            if actual_dim is None:
                self._vec_off_reason = "embed"
                self._embed_degraded_at = time.monotonic()
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
                    "dropping vec tables (facts in smart_archive_facts/graph_facts are kept)",
                    stored_dim, actual_dim,
                )
                await self.db.db.execute("DROP TABLE smart_archive")
                await self.db.db.execute("DROP TABLE IF EXISTS graph_facts_vec")
            await self.db.db.execute(_VEC_TABLE_SQL.format(dim=actual_dim))
            await self.db.db.execute(_GRAPH_VEC_TABLE_SQL.format(dim=actual_dim))
            await self.db.db.commit()
            self._vec_dim = actual_dim
            self._vec_available = True
            self._vec_off_reason = None
            logger.info("SmartModule: sqlite-vec loaded (dim=%d)", actual_dim)
            fire_and_forget(self.backfill_archive_vectors(), "backfill")
            return True
        except Exception:
            self._vec_off_reason = "extension"
            logger.warning(
                "SmartModule: sqlite-vec unavailable — FTS5 fallback (R3)",
                exc_info=True,
            )
            return False

    async def _embed(self, texts) -> list[list[float]]:
        """R46-8 (55.8): ретраи 3× с backoff 1.0*2**n на любых ошибках embed
        (в т.ч. эпизодических 403) — поверх LLMClient-ретраев 429/5xx."""
        last_exc = None
        for attempt in range(_EMBED_RETRY_ATTEMPTS):
            try:
                return await self.llm.embed(texts)
            except Exception as exc:
                last_exc = exc
                if attempt < _EMBED_RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(_EMBED_RETRY_BACKOFF * (2 ** attempt))
        raise last_exc

    async def _ensure_vec_retry(self) -> bool:
        """55.8: если vec выключен ИЗ-ЗА EMBED-фейла (не extension) и прошёл
        _VEC_REACTIVATE_INTERVAL — повторный probe; успех → создание vec-таблиц
        (модуль уже загружен в коннекшн) + backfill. Вызывается в начале
        vector_search() и _search_graph_facts(). Lock против гонок."""
        if self._vec_available or self._vec_off_reason != "embed":
            return self._vec_available
        if time.monotonic() - self._embed_degraded_at < _VEC_REACTIVATE_INTERVAL:
            return False
        async with self._reactivate_lock:
            if self._vec_available:
                return True
            try:
                vectors = await self._embed(["probe"])
                actual_dim = len(vectors[0]) if vectors and vectors[0] else None
            except Exception as exc:
                self._embed_degraded_at = time.monotonic()
                logger.warning("SmartModule: vec re-probe failed (%s) — still FTS5", exc)
                return False
            if actual_dim is None:
                return False
            try:
                await self.db.db.execute(_VEC_TABLE_SQL.format(dim=actual_dim))
                await self.db.db.execute(_GRAPH_VEC_TABLE_SQL.format(dim=actual_dim))
                await self.db.db.commit()
            except Exception:
                logger.warning("SmartModule: vec tables recreate failed", exc_info=True)
                return False
            self._vec_dim = actual_dim
            self._vec_available = True
            self._vec_off_reason = None
            logger.info("SmartModule: vec reactivated after embed recovery | dim=%d",
                        actual_dim)
            fire_and_forget(self.backfill_archive_vectors(), "backfill")
            return True

    async def backfill_archive_vectors(self) -> int:
        """R46-8 (55.8): re-embedding фактов L3 без векторов (dim-сдвиг/403-эпизод).
        Батчи _BACKFILL_BATCH, потолок _BACKFILL_MAX_FACTS за вызов; существующие
        vec-строки НЕ дублируются (existence-check). НЕ бросает."""
        if not self._vec_available:
            return 0
        try:
            cursor = await self.db.db.execute(
                "SELECT id, fact, chat_id FROM smart_archive_facts "
                "WHERE id NOT IN (SELECT fact_id FROM smart_archive) LIMIT ?",
                (_BACKFILL_MAX_FACTS,))
            rows = await cursor.fetchall()
            processed = 0
            for start in range(0, len(rows), _BACKFILL_BATCH):
                batch = rows[start:start + _BACKFILL_BATCH]
                try:
                    vectors = await self._embed([row["fact"] for row in batch])
                except Exception:
                    logger.warning("SmartModule backfill: embed failed — deferred | processed=%d",
                                   processed)
                    break
                for row, vector in zip(batch, vectors):
                    await self.db.db.execute(
                        "INSERT INTO smart_archive(rowid, fact_id, chat_id, embedding) "
                        "VALUES (?, ?, ?, ?)",
                        (row["id"], row["id"], row["chat_id"], json.dumps(vector)))
                await self.db.db.commit()
                processed += len(batch)
            if processed:
                logger.info("SmartModule backfill: re-embedded %d facts", processed)
            return processed
        except Exception:
            logger.warning("SmartModule backfill: failed", exc_info=True)
            return 0

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
        await self._ensure_vec_retry()          # Epic 46 (55.8): deferred-реактивация
        if self._vec_available:
            try:
                vectors = await self._embed([query])
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
                self._embed_degraded_at = time.monotonic()   # vec жив, embed деградировал (55.8)
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

    # ── GraphRAG v2: Fact Extractor (Epic 46, Section 55.4) ───────

    async def memorize_facts(self, chat_id: int, raw_text: str, source_type: str) -> None:
        """R46-2 (55.4): raw_text → FACT_EXTRACT_PROMPT (канон R46-2) →
        триплеты → nodes/edges (entity_type='fact', origin/expires_at) +
        graph_facts (+vec0). Embed-фейл (403 и пр.) → факт сохраняется ТЕКСТОМ
        (FTS-фолбек), WARNING. Только сырая фактура источников — ответы бота
        сюда НЕ попадают (хуки передают raw, 55.5). chat_history → expires_at
        NULL (вечно); остальные → now + GRAPH_FACT_TTL_DAYS*86400 (D175)."""
        if not settings.GRAPH_RAG_ENABLED:
            return
        if source_type not in _FACT_ORIGINS:
            logger.warning("graphrag memorize: unknown source_type=%r — skipped", source_type)
            return
        try:
            await self._memorize_facts_inner(chat_id, raw_text, source_type)
        except Exception:
            logger.exception(
                "graphrag memorize: failed | chat_id=%s | source=%s", chat_id, source_type
            )

    async def _memorize_facts_inner(self, chat_id, raw_text, source_type) -> None:
        text = " ".join(str(raw_text).split())
        if not text:
            return
        tail = text[-_FACT_EXTRACT_MAX_CHARS:]
        raw = await self.llm.generate([
            {"role": "system", "content": FACT_EXTRACT_PROMPT},
            {"role": "user", "content": tail},
        ])
        facts = parse_fact_list(raw)
        if not facts:
            logger.info("graphrag memorize: 0 facts | chat_id=%s | source=%s",
                        chat_id, source_type)
            return
        expiry = None if source_type == "chat_history" else \
            int(time.time()) + settings.GRAPH_FACT_TTL_DAYS * 86400
        saved = 0
        for fact in facts:
            sid = await self.db.upsert_node(
                chat_id, fact["subject"], "fact", origin=source_type, expires_at=expiry)
            oid = await self.db.upsert_node(
                chat_id, fact["object"], "fact", origin=source_type, expires_at=expiry)
            await self.db.upsert_edge(
                sid, oid, fact["predicate"], origin=source_type, expires_at=expiry)
            sentence = f"{fact['subject']} {fact['predicate']} {fact['object']}"
            if fact["context"]:
                sentence += f" ({fact['context']})"
            fact_id = await self.db.insert_graph_fact(
                chat_id, sentence, source_type, expiry)
            if self._vec_available:
                await self._save_graph_fact_embedding(
                    fact_id, chat_id, sentence, source_type, expiry)
            saved += 1
        logger.info("graphrag memorize: facts=%d | chat_id=%s | source=%s",
                    saved, chat_id, source_type)

    async def _save_graph_fact_embedding(self, fact_id, chat_id, fact, origin,
                                         expires_at) -> None:
        try:
            vectors = await self._embed([fact])          # ретраи 55.8
            await self.db.db.execute(
                "INSERT INTO graph_facts_vec(rowid, fact_id, chat_id, origin, "
                "expires_at, embedding) VALUES (?, ?, ?, ?, ?, ?)",
                (fact_id, fact_id, chat_id, origin, expires_at,
                 json.dumps(vectors[0])))
            await self.db.db.commit()
        except Exception:
            logger.warning(
                "[graphrag] embed failed — fact saved text-only | fact_id=%d",
                fact_id, exc_info=True)

    # ── GraphRAG v2: гибридный RAG (Epic 46, Section 55.6) ────────

    async def get_rag_context(self, chat_id: int, query: str) -> str:
        """Гибридный RAG (55.6): векторный поиск по graph_facts_vec (KNN) →
        FTS5-фолбек (graph_facts_fts). Ленивый TTL (D175). Возвращает КАНОН-XML
        или "". НИКОГДА не бросает (любая ошибка → WARNING → "")."""
        if not settings.GRAPH_RAG_ENABLED:
            return ""
        try:
            facts = await self._search_graph_facts(
                chat_id, str(query or ""), settings.GRAPH_RAG_FACTS_LIMIT)
        except Exception:
            logger.warning("graphrag RAG: search failed — empty context | chat_id=%s",
                           chat_id, exc_info=True)
            return ""
        context = build_rag_context(facts)
        if context and len(context) > settings.GRAPH_RAG_CONTEXT_MAX_CHARS:
            logger.warning("graphrag RAG: context truncated to %d chars | chat_id=%s",
                           settings.GRAPH_RAG_CONTEXT_MAX_CHARS, chat_id)
            context = context[:settings.GRAPH_RAG_CONTEXT_MAX_CHARS]
        if context:
            logger.info("graphrag RAG: facts=%d | chat_id=%s | chars=%d",
                        len(facts), chat_id, len(context))
        return context

    async def _search_graph_facts(self, chat_id, query, limit) -> list:
        """[(origin, fact), ...]. Vec-путь: _ensure_vec_retry (55.8) → KNN;
        фейл embed/vec → FTS-фолбек. Оба пустых → []. НЕ бросает."""
        now = int(time.time())
        if await self._ensure_vec_retry():
            try:
                vectors = await self._embed([query])
                if vectors and vectors[0]:
                    rows = await self._knn_graph_facts(chat_id, vectors[0], limit)
                    if rows:
                        return rows
            except Exception:
                self._embed_degraded_at = time.monotonic()
                logger.warning("graphrag RAG: KNN failed — FTS fallback | chat_id=%s",
                               chat_id, exc_info=True)
        keywords = _TOKEN_RE.findall(str(query).lower())
        match_query = build_fts_query(keywords)
        if not match_query:
            return []
        rows = await self.db.search_graph_facts_fts(chat_id, match_query, limit, now)
        return [(row["origin"], row["fact"]) for row in rows]

    async def _knn_graph_facts(self, chat_id, vector, limit) -> list:
        now = int(time.time())
        cursor = await self.db.db.execute(
            "SELECT fact_id, chat_id, origin, expires_at, distance FROM graph_facts_vec "
            "WHERE embedding MATCH ? AND k = ?",
            (json.dumps(vector), limit * 2))
        rows = await cursor.fetchall()
        kept = [
            (row["fact_id"], row["origin"]) for row in rows
            if row["chat_id"] == chat_id
            and (row["expires_at"] is None or row["expires_at"] > now)
        ][:limit]
        if not kept:
            return []
        return await self.db.get_graph_fact_texts([fid for fid, _ in kept])

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
        # Epic 46 (55.1 #5, D175): piggyback-очистка истёкших GraphRAG v2-фактов
        # (крон 4×/день + ручной /summary; отдельный APScheduler-джоб не вводим).
        try:
            await self.db.purge_expired_graph_facts(chat_id)
        except Exception:
            logger.warning(
                "graphrag purge: expired-facts purge failed | chat_id=%s",
                chat_id, exc_info=True,
            )

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
