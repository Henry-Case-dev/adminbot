"""Epic 24 — three-level chat memory manager (R2/R3, Section 33.5).

L1: generation window (SUMMARY_WINDOW_HOURS), one SQL pass.
L2: raw messages for FTS5-RAG (FULL_MEMORY_RETENTION_DAYS).
L3: compressed archive facts + sqlite-vec KNN with mandatory FTS5 fallback.

Epic 46 (Section 55): GraphRAG v2 — memorize_facts (Fact Extractor, канон
R46-2), гибридный RAG (build_rag_context, канон R46-4), fire_and_forget-хуки,
фиксы диагностики 55.8 (_embed-ретраи, vec-реактивация, backfill).

Фаза 2 (импорт истории, T-756): тумблер memory.infinite_retention — список
точек-гейтов (самодокументация; ON = «сырьё и факты памяти не удаляются и
не сжимаются по TTL/ретенции», для исторического импорта):
  G1  compress_and_purge — extract-only ветка: _extract_and_save_graph по
      пачкам старых сообщений БЕЗ сжатия/удаления сырья и БЕЗ записи
      smart_archive; пачки импортированных строк (import_key IS NOT NULL)
      исключаются из extract (get_smart_raw exclude_imported=True) — их
      графом пополняет только Graph-воркер (history_processed);
      обработанные live-строки помечаются history_processed=1
      (mark_smart_messages_processed) — выборка extract берёт
      history_processed=0 AND import_key IS NULL (общая колонка с воркером,
      наборы строк дизъюнктны: воркер — import_key IS NOT NULL);
  G2  _purge_archive — skip (no-op; архив живёт до OFF);
  G3  database.purge_expired_graph_facts — return 0 (гейт в db-слое);
  G4  database.purge_unconfirmed_graph_facts — return 0 (гейт в db-слое);
  G5  database.trim_compression_log — return 0 (гейт в db-слое);
  G6  memory_maintenance.review — фазы expired/unconfirmed/trim скипаются
      самими гейтами G3-G5; merge-фазы (слияние, не удаление) работают.
Явные команды «забудь»/«/clear» работают всегда (гейтов не имеют).
"""
import asyncio
import calendar
import datetime
import hashlib
import json
import logging
import math
import re
import struct
import time

from config.settings import settings
from services.database import row_get
from services import hot_config as hot
from services.llm_client import LLMError
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

# Epic 60 (66.6, T-484): int8-схема — float-канон + int8-coarse (двухпроходный
# поиск: грубый KNN по int8 → реранк точной cosine по float). Вставка —
# vec_quantize_int8(vector, 'unit') (sqlite-vec 0.1.9).
_VEC_TABLE_SQL_INT8 = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS smart_archive USING vec0("
    "embedding float[{dim}] distance_metric=cosine, embedding_i8 int8[{dim}], "
    "+fact_id INTEGER, +chat_id INTEGER)"
)

_GRAPH_VEC_TABLE_SQL_INT8 = (
    "CREATE VIRTUAL TABLE IF NOT EXISTS graph_facts_vec USING vec0("
    "embedding float[{dim}] distance_metric=cosine, embedding_i8 int8[{dim}], "
    "+fact_id INTEGER, +chat_id INTEGER, +origin TEXT, +expires_at INTEGER)"
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

_FACT_ORIGINS = ("chat_history", "search_fact", "youtube_content", "web_content",
                 "bot_direct_reply",
                 "voice_transcript",   # Epic 67: транскрипты voice/video_note
                 "video_transcript",   # Bugfix 04.09.2026 (Часть 1): TG-видео
                 "user_memory")        # Раунд 4 (T-713, 3.4.3): «запомни»-команды
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

# Epic 60 (64.4, T-465): кэш эмбеддингов — ленивый last_used_at только если
# старше 60с (без write-per-read); LRU-cap и TTL — см. EMBED_CACHE_*.
_EMBED_TOUCH_SECONDS = 60.0
# Epic 60 (64.6, T-467): потолок head-текста в конспект-запрос (дефенсив,
# окно 500×2000 симв в один prompt не влезает).
_RUNNING_SUMMARY_HEAD_MAX_CHARS = 60000


def _embed_cache_key(text: str) -> str:
    """64.4: SHA-256(casefold + strip) — канон-ключ embedding_cache."""
    return hashlib.sha256(str(text).casefold().strip().encode("utf-8")).hexdigest()


# ── Epic 60 Фаза D (66.1/66.3/66.8, T-479/T-481/T-486) ─────────

def _clamp_weight(value: float) -> float:
    """66.1: вес 0..1; значения вне диапазона клампятся с WARNING."""
    w = float(value)
    if not 0.0 <= w <= 1.0:
        logger.warning("graphrag weight %s outside [0,1] — clamped (66.1)", w)
        return min(1.0, max(0.0, w))
    return w


def _origin_weight(source_type: str) -> float:
    """66.1 (T-479): начальный вес по origin. chat_history 0.5 (канон);
    bot_direct_reply — GRAPH_FACT_WEIGHT_DIRECT (личная просьба важнее фона);
    архивные (search_fact/youtube_content/web_content) — GRAPH_FACT_WEIGHT_ARCHIVE.
    user_memory (раунд 4, T-713): явная команда «запомни» — вес 1.0 (максимум)."""
    if source_type == "bot_direct_reply":
        return _clamp_weight(hot.get("limits.graph_fact_weight_direct", settings.GRAPH_FACT_WEIGHT_DIRECT))
    if source_type == "chat_history":
        return 0.5
    if source_type == "user_memory":
        return 1.0
    return _clamp_weight(hot.get("limits.graph_fact_weight_archive", settings.GRAPH_FACT_WEIGHT_ARCHIVE))


def _effective_weight(weight, confirmed_at, now: int) -> float:
    """66.3 (T-481): w_eff = weight × 0.5^(Δдней/half_life) от last_confirmed_at;
    floor GRAPH_TIME_DECAY_FLOOR. Decay — ТОЛЬКО множитель ранга при чтении
    (ничего не удаляется). Выключатель → weight как есть."""
    if not hot.get("flags.graph_time_decay_enabled", settings.GRAPH_TIME_DECAY_ENABLED):
        return float(weight or 0.5)
    if confirmed_at is None:
        confirmed_at = now
    days = max(0.0, (now - confirmed_at) / 86400.0)
    # N2: half_life в знаменателе — 0/NULL не даёт ZeroDivisionError (max 1)
    half_life = max(1.0, hot.get(
        "limits.graph_time_decay_half_life_days",
        settings.GRAPH_TIME_DECAY_HALF_LIFE_DAYS) or 1.0)
    w_eff = float(weight or 0.5) * (0.5 ** (days / half_life))
    # N4: floor — or 0 по смыслу (пол не может быть None)
    return max(hot.get("limits.graph_time_decay_floor",
                       settings.GRAPH_TIME_DECAY_FLOOR) or 0.0, w_eff)


def _cosine(a, b) -> float:
    """Чистая cosine-сходство двух float-векторов (без numpy — R60-34)."""
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for x, y in zip(a, b):
        dot += x * y
        norm_a += x * x
        norm_b += y * y
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


def _mmr_select(sims: list, limit: int, lam: float) -> list:
    """66.8 (T-486): жадный MMR. sims: [(item, rel, vector), ...] — rel =
    cosine(query, item) × w_eff (вес+затухание 66.1/66.3), vector — float-вектор
    факта для диверсификации. score = λ·rel − (1−λ)·max_sim(item, выбранные).
    Сначала самый релевантный, затем argmax по остатку. Сложность O(k×fetch_k)."""
    if len(sims) <= limit:
        return [item for item, _, _ in sims]
    remaining = list(sims)
    first = max(remaining, key=lambda s: s[1])
    selected = [first]
    remaining.remove(first)
    while len(selected) < limit and remaining:
        def score(candidate):
            if candidate[2] is None:
                diversity = 0.0
            else:
                others = [chosen[2] for chosen in selected if chosen[2] is not None]
                diversity = (max(_cosine(candidate[2], vec) for vec in others)
                             if others else 0.0)
            return lam * candidate[1] - (1.0 - lam) * diversity
        best = max(remaining, key=score)
        selected.append(best)
        remaining.remove(best)
    return [item for item, _, _ in selected]

_RAG_PREFIXES = {
    "search_fact": "[Из твоего прошлого поиска]: ",
    "youtube_content": "[Из видео, которое кидали ранее]: ",
    "web_content": "[Из статьи]: ",
}

# Раунд 8 (F3/T-809, spec §3.F3.1): origin-метки direct-рендера RAG — рядом
# с _RAG_PREFIXES (легаси), значения _RAG_PREFIXES НЕ меняются. Формат строки
# direct: "[{label}] {date_prefix}{текст}"; неизвестный origin — сам origin.
_ORIGIN_LABELS = {
    "chat_history": "чат",
    "bot_direct_reply": "личный диалог",
    "search_fact": "поиск",
    "youtube_content": "видео",
    "web_content": "статья",
    "voice_transcript": "голосовое",
    "video_transcript": "видео",
    "user_memory": "запомнено",
    "history_import": "история",
}

# Раунд 8 (F4/T-810, spec §3.F4.2): компактный утилитарный промпт LLM-реранка
# RAG-фактов direct (по образцу search_service Epic 65) — НЕ канон, вне PG.
_CHAT_RAG_RERANK_SYSTEM_PROMPT = (
    "Ты — фильтр фактов памяти для ответа в чате. Тебе даны запрос и "
    "нумерованный список фактов. Верни ТОЛЬКО номера фактов, реально "
    "релевантных запросу, через запятую. Ничего не комментируй. Если "
    "релевантного нет — верни 0."
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
        if len(triplets) >= (hot.get("limits.graph_extract_max_triplets", settings.GRAPH_EXTRACT_MAX_TRIPLETS) or 0):
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
        if len(facts) >= (hot.get("limits.graph_extract_max_triplets", settings.GRAPH_EXTRACT_MAX_TRIPLETS) or 0):
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
    НЕ всплывает в чат (исключение не теряется — ловится здесь).
    Epic 47 (D190, 56.7 #11): ожидаемый LLMError → WARNING без exc_info;
    неожиданное Exception → WARNING + exc_info."""
    async def _run() -> None:
        try:
            await coro
        except LLMError as exc:
            logger.warning("[graphrag hook] %s failed: %s", tag, exc)
        except Exception:
            logger.warning("[graphrag hook] %s failed", tag, exc_info=True)
    asyncio.create_task(_run())


# ── Раунд 3 (3.7/C2, T-697): TTL bot_direct_reply ──────────────────────

_DIRECT_REPLY_TTL_KEY = "limits.chat_direct_reply_ttl_days"
_DIRECT_REPLY_TTL_DEFAULT = 30


async def migrate_direct_reply_ttl_default(cache) -> bool:
    """FR-C2 (T-697): миграция прод-значения PG по образцу
    migrate_prompt_canons (services/prompt_migrations.py, раунд 5; ранее —
    migrate_direct_chat_prompt_if_legacy в chat_prompts.py): легаси-сид
    (NULL/пусто) → 30; значение 0 или число (явный выбор/уже мигрировано) →
    не трогаем. Отсутствующий ключ неразличим с NULL (cache.get → None) —
    ставим 30 и в этом случае (сид ConfigCache сделал бы то же самое).
    PG down → skip (R6). True = значение обновлено."""
    if cache is None or not getattr(cache, "pg_available", False):
        logger.info("[ttl_migration] skip: PG недоступен")
        return False
    current = cache.get(_DIRECT_REPLY_TTL_KEY)
    if current is None:
        await cache.set(_DIRECT_REPLY_TTL_KEY, _DIRECT_REPLY_TTL_DEFAULT,
                        "limits")
        logger.info("[ttl_migration] ключ отсутствует/NULL — сид 30")
        return True
    if isinstance(current, str) and not str(current).strip():
        await cache.set(_DIRECT_REPLY_TTL_KEY, _DIRECT_REPLY_TTL_DEFAULT,
                        "limits")
        logger.info("[ttl_migration] легаси-пусто заменён на %d",
                    _DIRECT_REPLY_TTL_DEFAULT)
        return True
    if str(current).strip().lower() in ("none", "null"):
        await cache.set(_DIRECT_REPLY_TTL_KEY, _DIRECT_REPLY_TTL_DEFAULT,
                        "limits")
        logger.info("[ttl_migration] легаси-NULL заменён на %d",
                    _DIRECT_REPLY_TTL_DEFAULT)
        return True
    return False


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
    except LLMError as exc:
        logger.warning("[graphrag hook] youtube compress failed: %s", exc)
    except Exception:
        logger.warning("[graphrag hook] youtube compress failed", exc_info=True)


def _date_prefix(created_at) -> str:
    """Раунд 4 (T-724, FR-F1, spec 3.6): '[%Y-%m-%d] ' из unix-ts (UTC);
    None/0/пусто → ''. Никогда не бросает (RAG не роняет мусорным ts)."""
    if not created_at:
        return ""
    try:
        return datetime.datetime.fromtimestamp(
            int(created_at), datetime.timezone.utc).strftime("[%Y-%m-%d] ")
    except (ValueError, OSError, OverflowError):
        return ""


def _format_origin_labeled_line(item) -> str:
    """Раунд 8 (F3/T-809, spec §3.F3.1): одна строка direct-рендера RAG —
    '[{label}] {date_prefix}{текст}' (label из _ORIGIN_LABELS; неизвестный
    origin — сам origin; date_prefix — существующий '[%Y-%m-%d] '). Текст —
    через escape_xml_text (как легаси-рендер build_rag_context)."""
    origin = item[0]
    fact = item[1]
    date = _date_prefix(item[2]) if len(item) >= 3 else ""
    label = _ORIGIN_LABELS.get(origin, origin)
    return f"[{label}] {date}{escape_xml_text(fact)}"


def build_rag_context(facts: list, *, origin_labels: bool = False) -> str:
    """R46-4 (55.6): КАНОН-структура `<context>/<user_gossip>/<bot_knowledge>`.
    facts: (origin, fact) — БЕЗ даты (legacy, старые вызовы/тесты) ИЛИ
    (origin, fact, created_at) — дата-префикс '[%Y-%m-%d] ' (UTC) ПЕРЕД текстом
    (gossip: chat_history → user_gossip) и ПЕРЕД origin-префиксом (knowledge:
    остальные origin → bot_knowledge; unknown origin — без префикса). Дата
    добавляется ВСЕМ origin, где created_at есть. escape_xml_text ОБЯЗАТЕЛЕН
    (summary_xml). Пустые факты → "". Формат байт-в-байт (два пробела отступа;
    пустой блок — `<block></block>`); legacy-2-кортежи — ровно как раньше.
    Раунд 8 (F3/T-809): origin_labels=True → строки в едином формате
    '[{label}] {date_prefix}{текст}' (_format_origin_labeled_line) БЕЗ
    устаревшей группировки user_gossip/bot_knowledge — direct-рендер
    `<RAG_Memory>` (модель видит источник напрямую); дефолт False — легаси
    структура byte-for-byte без изменений (search/factcheck/тесты)."""
    if origin_labels:
        if not facts:
            return ""
        return "\n".join(_format_origin_labeled_line(item) for item in facts)
    gossip, knowledge = [], []
    for item in facts:
        origin = item[0]
        fact = item[1]
        date = _date_prefix(item[2]) if len(item) >= 3 else ""
        text = escape_xml_text(fact)
        if origin == "chat_history":
            gossip.append(date + text)
        else:
            knowledge.append(date + _RAG_PREFIXES.get(origin, "") + text)
    if not gossip and not knowledge:
        return ""
    lines = ["<context>",
             "  <user_gossip>" + "\n".join(gossip) + "</user_gossip>",
             "  <bot_knowledge>" + "\n".join(knowledge) + "</bot_knowledge>",
             "</context>"]
    return "\n".join(lines)


def _fact_tokens(text) -> set[str]:
    """F2 (T-808): нормализованные токены факта/строки фона для словарного
    дедупа (regex-токены, casefold) — нормализация 'lower, без дат-префиксов'."""
    return set(_TOKEN_RE.findall(str(text or "").casefold()))


def dedup_rag_vs_global(facts: list, global_text: str,
                        *, overlap_ratio: float | None = None) -> list:
    """Раунд 8 (F2/T-808, spec §3.F2): отфильтровать RAG-3-кортежи
    (origin, fact, created_at), чей текст «покрывается» строкой
    Global_Context (конспект/verbatim-хвост): доля токенов факта, найденных
    в ОДНОЙ строке фона, >= limits.chat_rag_dedup_overlap_ratio (default 0.8)
    при длине факта >= 3 токенов → дубль (детерминированный словарный метод;
    embedding-вариант отклонён — словарного покрытия достаточно). Исходный
    порядок rel сохраняется. Чистая функция, никогда не бросает (любая
    ошибка/кривой аргумент → факты остаются, WARNING — NFR-6 fail-open)."""
    if overlap_ratio is None:
        overlap_ratio = float(hot.get(
            "limits.chat_rag_dedup_overlap_ratio",
            settings.CHAT_RAG_DEDUP_OVERLAP_RATIO) or 0.8)
    try:
        if not facts or not str(global_text or "").strip():
            return list(facts)
        lines = [ln for ln in str(global_text).split("\n") if ln.strip()]
        if not lines:
            return list(facts)
        line_tokens = [_fact_tokens(ln) for ln in lines]
        kept: list = []
        for item in facts:
            fact_text = item[1] if isinstance(item, (tuple, list)) and \
                len(item) >= 2 else None
            tokens = _fact_tokens(fact_text)
            if len(tokens) < 3:
                kept.append(item)                 # короткие факты не дедупим
                continue
            covered = max(len(tokens & lt) / len(tokens) for lt in line_tokens)
            if covered < overlap_ratio:
                kept.append(item)
        return kept
    except Exception:
        logger.warning(
            "graphrag RAG: dedup vs global failed — facts kept (F2)", exc_info=True)
        return list(facts)


def _pack_vector(vector: list[float]) -> bytes:
    """Epic 64: упаковка вектора в float16 BLOB (6144 Б при dim=3072) вместо
    JSON-строки (~46 КБ) — ×7.5 меньше на строку embedding_cache."""
    return struct.pack(f"<{len(vector)}e", *vector)


def _unpack_vector(raw) -> list[float] | None:
    """Читает float16 BLOB (формат Epic 64) или JSON-строку (legacy до 64).
    None → битая запись (пропустить → miss → вектор перезапишется из API)."""
    if isinstance(raw, (bytes, bytearray)):
        try:
            return list(struct.unpack(f"<{len(raw) // 2}e", raw))
        except struct.error:
            return None
    if isinstance(raw, str):
        try:
            data = json.loads(raw)
        except (ValueError, TypeError):
            return None
        return data if isinstance(data, list) else None
    return None


class MemoryManager:
    """Owns L1/L2 access and the L3 archive (text + optional vec0).

    Epic 46 (55.8): _vec_off_reason «extension»|«embed», deferred-реактивация
    после embed-фейла (re-probe раз в _VEC_REACTIVATE_INTERVAL), backfill.
    """

    def __init__(self, db, llm, aliases=None) -> None:
        self.db = db
        self.llm = llm
        # Epic 60 (66.9, T-487): aliases — привязка фактов к людям по алиасам
        # (канон-имена в фактах/узлах; карточки /persona агрегируются по ним).
        self.aliases = aliases
        self._vec_available = False
        self._vec_dim = None
        self._vec_off_reason: str | None = None      # "extension" | "embed"
        self._embed_degraded_at = 0.0
        self._reactivate_lock = asyncio.Lock()
        # Epic 60 (66.6, T-484): int8-coarse + float-реранк (VEC_INT8_ENABLED).
        self._vec_int8 = False

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
            if actual_dim != int(hot.get("models.embedding_dim", settings.EMBEDDING_DIM)):
                logger.warning(
                    "SmartModule: EMBEDDING_DIM=%s != actual API dim=%d — using actual",
                    hot.get("models.embedding_dim", settings.EMBEDDING_DIM), actual_dim,
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
            # Epic 60 (66.6, T-484): int8-схема — float-канон + int8-coarse.
            # Существующая float-only таблица (Фаза B) → DROP + пересоздание;
            # backfill — из кэша эмбеддингов (без повторных API-вызовов).
            self._vec_int8 = bool(hot.get("flags.vec_int8_enabled", settings.VEC_INT8_ENABLED)) and \
                await self._probe_vec_int8()
            await self._rebuild_vec_tables_if_needed()
            await self.db.db.execute(
                self._vec_table_sql(actual_dim))
            await self.db.db.execute(
                self._graph_vec_table_sql(actual_dim))
            await self.db.db.commit()
            self._vec_dim = actual_dim
            self._vec_available = True
            self._vec_off_reason = None
            logger.info("SmartModule: sqlite-vec loaded (dim=%d, int8=%s)",
                        actual_dim, self._vec_int8)
            fire_and_forget(self.backfill_archive_vectors(), "backfill")
            fire_and_forget(self.backfill_graph_fact_vectors(), "backfill_graph")
            return True
        except Exception:
            self._vec_off_reason = "extension"
            logger.warning(
                "SmartModule: sqlite-vec unavailable — FTS5 fallback (R3)",
                exc_info=True,
            )
            return False

    def _vec_table_sql(self, dim: int) -> str:
        """66.6: DDL smart_archive — с int8-колонкой или float-only."""
        template = _VEC_TABLE_SQL_INT8 if self._vec_int8 else _VEC_TABLE_SQL
        return template.format(dim=dim)

    def _graph_vec_table_sql(self, dim: int) -> str:
        """66.6: DDL graph_facts_vec — с int8-колонкой или float-only."""
        template = _GRAPH_VEC_TABLE_SQL_INT8 if self._vec_int8 else _GRAPH_VEC_TABLE_SQL
        return template.format(dim=dim)

    async def _probe_vec_int8(self) -> bool:
        """66.6: дефенсив-проба vec_quantize_int8 (старые сборки sqlite-vec) —
        нет функции → float-only схема (честная деградация)."""
        try:
            cursor = await self.db.db.execute(
                "SELECT vec_quantize_int8('[0.0]', 'unit')")
            row = await cursor.fetchone()
            return row is not None
        except Exception:
            logger.warning(
                "SmartModule: vec_quantize_int8 unavailable — float-only (66.6)")
            return False

    async def _rebuild_vec_tables_if_needed(self) -> None:
        """66.6: существующая float-only vec-таблица при включённом int8 →
        DROP (ALTER у vec0 нет; shadow-таблицы RENAME не переносятся) +
        пересоздание; данные восстанавливаются backfill'ом из кэша (64.4)."""
        if not self._vec_int8:
            return
        for table in ("smart_archive", "graph_facts_vec"):
            cursor = await self.db.db.execute(
                "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,))
            row = await cursor.fetchone()
            if row and row["sql"] and "embedding_i8" not in row["sql"]:
                logger.warning(
                    "SmartModule: %s lacks embedding_i8 — rebuilding (66.6)", table)
                await self.db.db.execute(f"DROP TABLE {table}")
        await self.db.db.commit()

    async def _embed(self, texts) -> list[list[float]]:
        """64.4 (T-465): embedding_cache — батч-лукап SHA-256 → miss → API →
        write-back. Кэш покрывает ВСЕ вызовы _embed (probe/vector_search/
        memorize/backfill) — одна точка. Ошибки кэша НЕ блокируют (WARNING →
        обычный вызов API, 64.4). Ретраи 55.8 — внутри _embed_api.
        EMBED_CACHE_ENABLED=false → ровно старое поведение."""
        if not texts:
            return []
        if not hot.get("flags.embed_cache_enabled", settings.EMBED_CACHE_ENABLED):
            return await self._embed_api(texts)
        cached, misses = await self._embed_cache_lookup(texts)
        # Epic 64: hit-rate диагностика — данные для решения «нужен ли кэш».
        logger.info("embed cache | hits=%d misses=%d", len(cached), len(misses))
        results: dict[str, list[float]] = dict(cached)
        if misses:
            fetched = await self._embed_api(misses)
            await self._embed_cache_store(misses, fetched)
            results.update(zip(misses, fetched))
        return [results[text] for text in texts]

    async def _embed_api(self, texts) -> list[list[float]]:
        """R46-8 (55.8): ретраи 3× с backoff 1.0*2**n на любых ошибках embed
        (в т.ч. эпизодических 403) — поверх LLMClient-ретраев 429/5xx.
        Задача 3 (01.09.2026): диаг-логи попыток — тип/код ошибки (у
        LLMAuthError теперь есть обрезанное тело провайдера) + провайдер;
        финальный фейл логируется ERROR и пробрасывается (KNN→FTS-каскад
        решает деградацию ниже по стеку)."""
        last_exc = None
        for attempt in range(_EMBED_RETRY_ATTEMPTS):
            try:
                return await self.llm.embed(texts)
            except Exception as exc:
                last_exc = exc
                logger.warning(
                    "embed attempt failed | attempt=%d/%d | error=%s",
                    attempt + 1, _EMBED_RETRY_ATTEMPTS,
                    f"{type(exc).__name__}: {exc}",
                )
                if attempt < _EMBED_RETRY_ATTEMPTS - 1:
                    await asyncio.sleep(_EMBED_RETRY_BACKOFF * (2 ** attempt))
        logger.error(
            "embed failed after %d attempts | error=%s",
            _EMBED_RETRY_ATTEMPTS,
            f"{type(last_exc).__name__}: {last_exc}",
        )
        raise last_exc

    async def _embed_cache_lookup(self, texts) -> tuple[dict, list]:
        """Хиты {text: vector} + miss-тексты. НЕ бросает (любая ошибка БД →
        WARNING → все miss → API). Ленивый TTL-sweep; last_used_at продлевается
        ЛЕНИВО — только если старше _EMBED_TOUCH_SECONDS (64.4)."""
        try:
            now = time.time()
            ttl_seconds = (hot.get("limits.embed_cache_ttl_days", settings.EMBED_CACHE_TTL_DAYS) or 0) * 86400.0
            await self.db.db.execute(
                "DELETE FROM embedding_cache WHERE last_used_at < ?",
                (now - ttl_seconds,),
            )
            keys = [_embed_cache_key(text) for text in texts]
            unique = list(dict.fromkeys(keys))
            placeholders = ",".join("?" for _ in unique)
            cursor = await self.db.db.execute(
                f"SELECT text_hash, vector, dim, last_used_at FROM embedding_cache "
                f"WHERE text_hash IN ({placeholders})", unique,
            )
            rows = await cursor.fetchall()
            expected_dim = self._vec_dim or hot.get("models.embedding_dim", settings.EMBEDDING_DIM)
            by_hash: dict[str, list[float]] = {}
            touch: list[str] = []
            for row in rows:
                if row["dim"] != expected_dim:
                    continue                # dim-сдвиг (55.8) → miss, запишется заново
                try:
                    vector = _unpack_vector(row["vector"])
                except (ValueError, TypeError):
                    continue
                if vector is None:
                    continue
                by_hash[row["text_hash"]] = vector
                if isinstance(row["vector"], str):
                    # Epic 64: ленивая миграция legacy JSON → float16 BLOB.
                    try:
                        await self.db.db.execute(
                            "UPDATE embedding_cache SET vector = ? "
                            "WHERE text_hash = ?",
                            (_pack_vector(vector), row["text_hash"]),
                        )
                    except Exception:
                        pass
                if now - row["last_used_at"] > _EMBED_TOUCH_SECONDS:
                    touch.append(row["text_hash"])
            if touch:
                touch_ph = ",".join("?" for _ in touch)
                await self.db.db.execute(
                    f"UPDATE embedding_cache SET last_used_at = ? "
                    f"WHERE text_hash IN ({touch_ph})", (now, *touch),
                )
            await self.db.db.commit()
            cached: dict[str, list[float]] = {}
            misses: list[str] = []
            for text, key in zip(texts, keys):
                if key in by_hash:
                    cached[text] = by_hash[key]
                else:
                    misses.append(text)
            return cached, misses
        except Exception:
            logger.warning(
                "SmartModule: embedding cache lookup failed — API path",
                exc_info=True,
            )
            return {}, list(texts)

    async def _embed_cache_store(self, texts, vectors) -> None:
        """Write-back + ленивый TTL-sweep + LRU-cap (EMBED_CACHE_MAX_ROWS).
        НЕ бросает (WARNING — кэш не блокирует, 64.4). Кэш хранит float."""
        try:
            now = time.time()
            ttl_seconds = (hot.get("limits.embed_cache_ttl_days", settings.EMBED_CACHE_TTL_DAYS) or 0) * 86400.0
            await self.db.db.execute(
                "DELETE FROM embedding_cache WHERE last_used_at < ?",
                (now - ttl_seconds,),
            )
            cursor = await self.db.db.execute(
                "SELECT COUNT(*) AS c FROM embedding_cache")
            count = (await cursor.fetchone())["c"]
            if count + len(texts) > (hot.get("limits.embed_cache_max_rows", settings.EMBED_CACHE_MAX_ROWS) or 0):
                keep = max(0, (hot.get("limits.embed_cache_max_rows", settings.EMBED_CACHE_MAX_ROWS) or 0) - len(texts))
                await self.db.db.execute(
                    "DELETE FROM embedding_cache WHERE text_hash NOT IN "
                    "(SELECT text_hash FROM embedding_cache "
                    "ORDER BY last_used_at DESC LIMIT ?)", (keep,),
                )
            for text, vector in zip(texts, vectors):
                await self.db.db.execute(
                    "INSERT INTO embedding_cache "
                    "(text_hash, text, vector, dim, created_at, last_used_at) "
                    "VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(text_hash) DO UPDATE SET "
                    "text = excluded.text, vector = excluded.vector, "
                    "dim = excluded.dim, last_used_at = excluded.last_used_at",
                    (_embed_cache_key(text), text, _pack_vector(vector),
                     len(vector), now, now),
                )
            await self.db.db.commit()
        except Exception:
            logger.warning("SmartModule: embedding cache store failed",
                           exc_info=True)

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
                self._vec_int8 = bool(hot.get("flags.vec_int8_enabled", settings.VEC_INT8_ENABLED)) and \
                    await self._probe_vec_int8()
                await self._rebuild_vec_tables_if_needed()
                await self.db.db.execute(self._vec_table_sql(actual_dim))
                await self.db.db.execute(self._graph_vec_table_sql(actual_dim))
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
            fire_and_forget(self.backfill_graph_fact_vectors(), "backfill_graph")
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
                    # Epic 60 (64.4): existence-check ПЕРЕД INSERT — гонка с
                    # purge/параллельной записью (кэш эмбеддингов добавляет
                    # DB-кругляки — бэкфилл может догнать уже вставленную или
                    # уже удалённую строку; UNIQUE/orphan-дубль недопустимы).
                    cursor = await self.db.db.execute(
                        "SELECT id FROM smart_archive_facts WHERE id = ? "
                        "AND id NOT IN (SELECT fact_id FROM smart_archive)",
                        (row["id"],))
                    if await cursor.fetchone() is None:
                        continue
                    # 66.6 (T-484): int8-схема — две колонки.
                    if self._vec_int8:
                        await self.db.db.execute(
                            "INSERT INTO smart_archive(rowid, fact_id, chat_id, "
                            "embedding, embedding_i8) VALUES (?, ?, ?, ?, "
                            "vec_quantize_int8(?, 'unit'))",
                            (row["id"], row["id"], row["chat_id"],
                             json.dumps(vector), json.dumps(vector)))
                    else:
                        await self.db.db.execute(
                            "INSERT INTO smart_archive(rowid, fact_id, chat_id, "
                            "embedding) VALUES (?, ?, ?, ?)",
                            (row["id"], row["id"], row["chat_id"],
                             json.dumps(vector)))
                await self.db.db.commit()
                processed += len(batch)
            if processed:
                logger.info("SmartModule backfill: re-embedded %d facts", processed)
            return processed
        except Exception:
            logger.warning("SmartModule backfill: failed", exc_info=True)
            return 0

    async def backfill_graph_fact_vectors(self) -> int:
        """66.6 (T-484): re-embedding graph_facts без vec-строк (rebuild int8-
        таблицы / dim-сдвиг). Кэш эмбеддингов (64.4) делает это дешёвым — БЕЗ
        повторных API-вызовов. Те же батчи/потолок, что у архива (55.8). НЕ
        бросает."""
        if not self._vec_available:
            return 0
        try:
            now = int(time.time())
            cursor = await self.db.db.execute(
                "SELECT id, fact, chat_id, origin, expires_at FROM graph_facts "
                "WHERE id NOT IN (SELECT fact_id FROM graph_facts_vec) "
                "AND (expires_at IS NULL OR expires_at > ?) LIMIT ?",
                (now, _BACKFILL_MAX_FACTS))
            rows = await cursor.fetchall()
            processed = 0
            for start in range(0, len(rows), _BACKFILL_BATCH):
                batch = rows[start:start + _BACKFILL_BATCH]
                try:
                    vectors = await self._embed([row["fact"] for row in batch])
                except Exception:
                    logger.warning(
                        "SmartModule graph backfill: embed failed — deferred | "
                        "processed=%d", processed)
                    break
                for row, vector in zip(batch, vectors):
                    cursor = await self.db.db.execute(
                        "SELECT id FROM graph_facts WHERE id = ? "
                        "AND id NOT IN (SELECT fact_id FROM graph_facts_vec)",
                        (row["id"],))
                    if await cursor.fetchone() is None:
                        continue
                    await self._insert_graph_vec_row(
                        row["id"], row["chat_id"], row["fact"], row["origin"],
                        row["expires_at"], vector)
                await self.db.db.commit()
                processed += len(batch)
            if processed:
                logger.info("SmartModule graph backfill: re-embedded %d facts",
                            processed)
            return processed
        except Exception:
            logger.warning("SmartModule graph backfill: failed", exc_info=True)
            return 0

    async def _insert_graph_vec_row(self, fact_id, chat_id, fact, origin,
                                    expires_at, vector) -> None:
        """66.6: INSERT vec-строки graph_facts_vec (float-канон + int8-coarse
        при включённом int8)."""
        if self._vec_int8:
            await self.db.db.execute(
                "INSERT INTO graph_facts_vec(rowid, fact_id, chat_id, origin, "
                "expires_at, embedding, embedding_i8) VALUES (?, ?, ?, ?, ?, ?, "
                "vec_quantize_int8(?, 'unit'))",
                (fact_id, fact_id, chat_id, origin, expires_at,
                 json.dumps(vector), json.dumps(vector)))
        else:
            await self.db.db.execute(
                "INSERT INTO graph_facts_vec(rowid, fact_id, chat_id, origin, "
                "expires_at, embedding) VALUES (?, ?, ?, ?, ?, ?)",
                (fact_id, fact_id, chat_id, origin, expires_at,
                 json.dumps(vector)))

    @property
    def vec_available(self) -> bool:
        return self._vec_available

    # ── L1 window ──────────────────────────────────────────────

    async def get_window_messages(self, chat_id: int) -> list:
        """L1: messages within SUMMARY_WINDOW_HOURS, one SQL pass.
        Epic 60 (64.6, T-467): окно ≥ CHAT_CONTEXT_FILL_RATIO ×
        SUMMARY_MAX_WINDOW_MESSAGES и нет свежего конспекта → fire-and-forget
        бегущего конспекта (лениво, чат НЕ ждёт LLM)."""
        # N4: window_hours — or 0 (None из кэша → 0 = без окна, не падаем)
        since = int(time.time()) - int((hot.get(
            "limits.summary_window_hours", settings.SUMMARY_WINDOW_HOURS) or 0) * 3600)
        rows = await self.db.get_smart_window(
            chat_id, since, (hot.get("limits.summary_max_window_messages", settings.SUMMARY_MAX_WINDOW_MESSAGES) or 0)
        )
        logger.info(
            "SmartModule L1: window_size=%d | chat_id=%s | since_ts=%d",
            len(rows), chat_id, since,
        )
        fill_threshold = int(hot.get("limits.chat_context_fill_ratio", settings.CHAT_CONTEXT_FILL_RATIO)
                             * (hot.get("limits.summary_max_window_messages", settings.SUMMARY_MAX_WINDOW_MESSAGES) or 0))
        # T-619: флаг бегущего конспекта — горячая точка (фолбек settings)
        if hot.get("flags.chat_running_summary_enabled",
                   settings.CHAT_RUNNING_SUMMARY_ENABLED) and rows and \
                len(rows) >= fill_threshold:
            try:
                current = await self.db.get_running_summary(chat_id, time.time())
                last_ts = rows[-1]["timestamp"]
                if current is None or current["window_end_ts"] < last_ts:
                    fire_and_forget(
                        self._build_running_summary(chat_id, rows),
                        "running_summary",
                    )
            except Exception:
                logger.warning(
                    "SmartModule L1: running summary trigger check failed | chat_id=%s",
                    chat_id, exc_info=True,
                )
        return rows

    async def _build_running_summary(self, chat_id: int, rows: list) -> None:
        """64.6 (T-467): head окна → COMPRESS_PROMPT (канон-сосед R11 — новый
        промпт НЕ вводим); хвост CHAT_RUNNING_SUMMARY_TAIL — ДОСЛОВНО
        tail-блоком в тот же запрос. Результат → UPSERT в chat_running_summary
        (TTL RUNNING_SUMMARY_TTL_MINUTES — пишется, при чтении НЕ «убивает»,
        E4/T-806). LLMError → WARNING (fire_and_forget ловит). Вызывается
        ТОЛЬКО из fire_and_forget.
        Раунд 8 (E2/T-804, spec §3.E2.2): ПРЕДЫДУЩИЙ level-1 читается ДО
        upsert (после перезаписи его уже не достать), а после успешного
        upsert ПРЕДЫДУЩИЙ L1 сжимается в level 2 (wide) отдельной
        fire-and-forget-задачей _build_level2 — progressive summarization."""
        # E2: prev-L1 (до перезаписи) — кандидат на сжатие в level 2.
        prev_l1 = None
        try:
            prev_l1 = await self.db.get_running_summary(chat_id, time.time())
        except Exception:
            logger.warning(
                "running summary: prev-L1 read failed — level2 skipped "
                "| chat_id=%s", chat_id, exc_info=True)
        tail = (hot.get("limits.chat_running_summary_tail", settings.CHAT_RUNNING_SUMMARY_TAIL) or 0)
        head, tail_rows = rows[:-tail], rows[-tail:]
        if not head:
            return                          # нечего сжимать — конспект не нужен
        head_text = _build_batch_text(head, skip_empty=True)
        if len(head_text) > _RUNNING_SUMMARY_HEAD_MAX_CHARS:
            head_text = head_text[-_RUNNING_SUMMARY_HEAD_MAX_CHARS:]
        tail_text = _build_batch_text(tail_rows, skip_empty=True)
        user_content = head_text
        if tail_text:
            user_content += "\n\n=== последние сообщения дословно ===\n" + tail_text
        compress_prompt = hot.get("prompts.compress_system_prompt", COMPRESS_PROMPT)
        raw = await self.llm.generate([
            {"role": "system", "content": compress_prompt},
            {"role": "user", "content": user_content}])
        summary = str(raw or "").strip()
        if not summary:
            logger.warning("running summary: empty result | chat_id=%s", chat_id)
            return
        now = time.time()
        await self.db.upsert_running_summary(
            chat_id, summary, rows[0]["timestamp"], rows[-1]["timestamp"],
            len(rows), now, now + (hot.get("limits.running_summary_ttl_minutes", settings.RUNNING_SUMMARY_TTL_MINUTES) or 0) * 60.0)
        logger.info("running summary: built | chat_id=%s | chars=%d",
                    chat_id, len(summary))
        # E2/T-804: ПРЕДЫДУЩИЙ L1 (до перезаписи) — кандидат на сжатие в
        # level 2 (wide); порог raw_count и highwater-условие проверяются
        # внутри _build_level2 (до LLM-вызова). Первый конспект чата
        # (prev_l1 is None) L2 не строит — сжимать нечего.
        if prev_l1 is not None:
            fire_and_forget(self._build_level2(chat_id, prev_l1), "level2")

    async def _build_level2(self, chat_id: int, prev_l1_row: dict) -> None:
        """E2/T-804 (spec §3.E2.2): сжатие ПРЕДЫДУЩЕГО level-1 в level 2
        («широкий фон», chat_summary_levels) тем же COMPRESS_PROMPT (единый
        compress-канон — новая константа/миграция НЕ вводятся, Q13); user =
        текст prev-l1 конспекта. Условия запуска (здесь, ДО LLM):
        prev_l1.raw_count >= limits.chat_level2_min_raw_count (default 250)
        И (existing level-2 отсутствует ИЛИ его msg_count_highwater <
        prev_l1.raw_count — меньшим окном L2 не перезаписывается). Результат
        (непустой, ≤ 10 строк) → UPSERT (level=2) с msg_count_highwater =
        prev_l1.raw_count. Пустой/LLMError/ошибка БД → WARNING, без записи
        (fail-open, NFR-6). Вызывается ТОЛЬКО из fire_and_forget."""
        try:
            raw_count = int(prev_l1_row["raw_count"] or 0)
            min_raw = int(hot.get("limits.chat_level2_min_raw_count",
                                  settings.CHAT_LEVEL2_MIN_RAW_COUNT) or 0)
            if raw_count < (min_raw or 250):
                return
            existing = await self.db.get_summary_level(chat_id, 2)
            if existing is not None and \
                    int(existing["msg_count_highwater"] or 0) >= raw_count:
                return
            summary = str((await self.llm.generate([
                {"role": "system", "content": hot.get(
                    "prompts.compress_system_prompt", COMPRESS_PROMPT)},
                {"role": "user", "content": str(prev_l1_row["summary"] or "")}
            ])) or "").strip()
            if not summary:
                logger.warning(
                    "level2: empty compress result — no write | chat_id=%s",
                    chat_id)
                return
            lines = summary.split("\n")
            if len(lines) > 10:
                logger.warning(
                    "level2: compress result %d lines — capped to 10 | chat_id=%s",
                    len(lines), chat_id)
                summary = "\n".join(lines[:10])
            await self.db.upsert_summary_level(
                chat_id, 2, summary, time.time(), raw_count)
            logger.info("level2: built | chat_id=%s | chars=%d",
                        chat_id, len(summary))
        except Exception:
            logger.warning(
                "level2: build failed — no write | chat_id=%s",
                chat_id, exc_info=True)

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

    async def count_mentions(self, chat_id: int, keywords_: list[str],
                             since_ts: int = 0) -> dict | None:
        """Счётчик совпадений по тем же токенам, что search_long_term.
        None — пустой FTS-запрос (нечего считать). Ошибки БД — наружу
        (ToolRouter ловит → fail-open текст). Bugfix 04.09.2026 (Часть 2,
        FR-19): точный count + диапазон дат для query_chat_memory."""
        query = build_fts_query(keywords_)
        if not query:
            return None
        try:
            return await self.db.search_messages_fts_count(chat_id, query, since_ts)
        except Exception:
            logger.warning("SmartModule L2: count failed | chat_id=%s", chat_id, exc_info=True)
            raise

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
        # Epic 60 (66.6, T-484): int8 — грубый KNN k=limit×4 → реранк float →
        # top-limit; float-only — ровно старый точный MATCH.
        embedding_json = json.dumps(vector)
        if self._vec_int8:
            try:
                cursor = await self.db.db.execute(
                    "SELECT fact_id, chat_id FROM smart_archive "
                    "WHERE embedding_i8 MATCH vec_quantize_int8(?, 'unit') AND k = ?",
                    (embedding_json, limit * 4))
                rows = await cursor.fetchall()
            except Exception:
                logger.warning(
                    "SmartModule L3: int8 KNN failed — float path", exc_info=True)
                rows = None
            if rows is not None:
                ids = [row["fact_id"] for row in rows if row["chat_id"] == chat_id]
                if ids:
                    placeholders = ",".join("?" for _ in ids)
                    cursor = await self.db.db.execute(
                        f"SELECT rowid AS fact_id, embedding FROM smart_archive "
                        f"WHERE rowid IN ({placeholders})", ids)
                    vecs = {}
                    for row in await cursor.fetchall():
                        blob = row["embedding"]
                        try:
                            if isinstance(blob, str):
                                vec = json.loads(blob)
                            else:
                                vec = list(struct.unpack(
                                    f"<{len(bytes(blob)) // 4}f", bytes(blob)))
                            vecs[row["fact_id"]] = vec
                        except Exception:
                            continue
                    ranked = sorted(
                        ((fid, _cosine(vector, vec)) for fid, vec in vecs.items()),
                        key=lambda item: item[1], reverse=True)
                    ids = [fid for fid, _ in ranked[:limit]]
                    if ids:
                        placeholders = ",".join("?" for _ in ids)
                        cursor = await self.db.db.execute(
                            f"SELECT id, fact FROM smart_archive_facts "
                            f"WHERE id IN ({placeholders})", ids)
                        by_id = {row["id"]: row["fact"]
                                 for row in await cursor.fetchall()}
                        return [by_id[fid] for fid in ids if fid in by_id]
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

    async def memorize_facts(self, chat_id: int, raw_text: str, source_type: str,
                             target_user: str | None = None) -> None:
        """R46-2 (55.4): raw_text → FACT_EXTRACT_PROMPT (канон R46-2) →
        триплеты → nodes/edges (entity_type='fact', origin/expires_at) +
        graph_facts (+vec0). Embed-фейл (403 и пр.) → факт сохраняется ТЕКСТОМ
        (FTS-фолбек), WARNING. Только сырая фактура источников — ответы бота
        сюда НЕ попадают (хуки передают raw, 55.5). chat_history → expires_at
        NULL (вечно); остальные → now + GRAPH_FACT_TTL_DAYS*86400 (D175).
        Epic 50 (58.8, D205): source_type='bot_direct_reply' + target_user;
        TTL — CHAT_DIRECT_REPLY_TTL_DAYS (пусто/0 → expires_at NULL, вечное)."""
        if not hot.get("flags.graph_rag_enabled", settings.GRAPH_RAG_ENABLED):
            return
        if source_type not in _FACT_ORIGINS:
            logger.warning("graphrag memorize: unknown source_type=%r — skipped", source_type)
            return
        try:
            await self._memorize_facts_inner(chat_id, raw_text, source_type, target_user)
        except LLMError as exc:
            # Ожидаемое (timeout/429/5xx/транспорт после _post-ретраев) — WARNING
            # без traceback (Epic 47, D188/56.7 #9). Auth тоже «ожидаемый» фон.
            logger.warning(
                "graphrag memorize: LLM failed | chat_id=%s | source=%s | error=%s",
                chat_id, source_type, exc,
            )
        except Exception:
            logger.exception(
                "graphrag memorize: unexpected failure | chat_id=%s | source=%s",
                chat_id, source_type,
            )

    async def _extract_facts(self, tail: str) -> str:
        """R47-3/D188 (56.5): bounded-ретраи ПОСЛЕ _post-ретраев. Только LLMError.

        max_retry = GRAPH_MEMORIZE_MAX_BATCH_RETRIES (default 2 → 3 попытки),
        сон GRAPH_MEMORIZE_BATCH_RETRY_BACKOFF * 2**attempt (default 2.0/4.0).
        Канон FACT_EXTRACT_PROMPT (R46-2) — байт-в-байт, НЕ трогать.
        """
        max_retry = (hot.get("limits.graph_memorize_max_batch_retries", settings.GRAPH_MEMORIZE_MAX_BATCH_RETRIES) or 0)
        for attempt in range(max_retry + 1):
            try:
                return await self.llm.generate([
                    {"role": "system", "content": FACT_EXTRACT_PROMPT},
                    {"role": "user", "content": tail}])
            except LLMError as exc:
                if attempt < max_retry:
                    logger.info("graphrag memorize: extract retry | attempt=%d/%d | error=%s",
                                attempt + 1, max_retry + 1, exc)
                    await asyncio.sleep(
                        (hot.get("limits.graph_memorize_batch_retry_backoff", settings.GRAPH_MEMORIZE_BATCH_RETRY_BACKOFF) or 0) * (2 ** attempt))
                    continue
                raise exc

    async def _memorize_facts_inner(self, chat_id, raw_text, source_type,
                                    target_user=None) -> None:
        text = " ".join(str(raw_text).split())
        if not text:
            return
        tail = text[-_FACT_EXTRACT_MAX_CHARS:]
        raw = await self._extract_facts(tail)     # Epic 47 (D188): bounded-повтор
        facts = parse_fact_list(raw)
        if not facts:
            logger.info("graphrag memorize: 0 facts | chat_id=%s | source=%s",
                        chat_id, source_type)
            return
        # Раунд 8 (C4/T-795, spec §3.C4/Q4): «карта дисплеев» чата — участники
        # за limits.chat_map_participants_hours (тот же C2-запрос, что карта
        # UserResolutionMap). Subject/object факта, совпавшие (casefold) с
        # дисплей-именем участника, приводятся к канон-имени участника
        # (resolve-результат: алиас, если он есть; иначе его display). Чинит
        # привязку, когда nickname сменился при наличии алиаса. Смена ника
        # БЕЗ алиаса — факты не мигрируют (миграция запрещена): новые пишутся
        # по карте (канон == display), старое имя остаётся у старых фактов.
        # Ошибка БД на карте → факты пишутся ровно как раньше (fail-open).
        display_canons: dict[str, str] = {}
        try:
            display_canons = await self._participant_display_canons(chat_id)
        except Exception:
            logger.warning(
                "graphrag memorize: participant map failed — canon only "
                "| chat_id=%s | source=%s", chat_id, source_type, exc_info=True)
        # Epic 50 (58.8, D205): bot_direct_reply — TTL по CHAT_DIRECT_REPLY_TTL_DAYS
        # (пусто/0 → expires_at NULL, вечное — по ТЗ); chat_history — NULL;
        # остальные — GRAPH_FACT_TTL_DAYS (D175, без изменений).
        # Epic 60 (66.1, T-479): вес по origin; TTL = base × (0.5 + weight) —
        # важные факты живут дольше (прямой 0.7 → ×1.2; архивный 0.4 → ×0.9).
        weight = _origin_weight(source_type)
        if source_type == "chat_history":
            expiry = None
        elif source_type == "bot_direct_reply":
            ttl_days = (hot.get("limits.chat_direct_reply_ttl_days", settings.CHAT_DIRECT_REPLY_TTL_DAYS) or 0)
            expiry = None if ttl_days in (None, 0) else \
                int(time.time() + ttl_days * 86400.0 * (0.5 + weight))
        else:
            expiry = int(time.time()
                         + (hot.get("limits.graph_fact_ttl_days", settings.GRAPH_FACT_TTL_DAYS) or 0) * 86400.0 * (0.5 + weight))
        saved = 0
        skipped = 0
        deduped = 0
        superseded = 0
        for i, fact in enumerate(facts, 1):
            try:
                # Epic 60 (66.9, T-487): привязка к людям по алиасам —
                # subject/object приводятся к канон-имени алиаса (карточки
                # /persona агрегируются по одному имени).
                # Раунд 8 (C4/T-795): + карта дисплеев чата — display-имя
                # участника → канон (смена ника при наличии алиаса).
                subject = self._canon_fact_name(fact["subject"])
                obj = self._canon_fact_name(fact["object"])
                subject = display_canons.get(subject.casefold(), subject)
                obj = display_canons.get(obj.casefold(), obj)
                sentence = f"{subject} {fact['predicate']} {obj}"
                if fact["context"]:
                    sentence += f" ({fact['context']})"
                # ── 64.1/64.2 (T-462/T-463): дедуп перед записью ──
                # Вектор для дедупа переиспользуется при сохранении
                # vec-строки (второй вызов embed НЕ делаем). Ошибка embed →
                # факт пишется как раньше (64.1.5).
                vector = None
                if hot.get("flags.graph_dedup_enabled", settings.GRAPH_DEDUP_ENABLED) and self._vec_available:
                    try:
                        vectors = await self._embed([sentence])
                        if vectors and vectors[0]:
                            vector = vectors[0]
                    except Exception:
                        logger.warning(
                            "graphrag dedup: embed failed — check skipped | fact #%d", i)
                dedup_fact = {"subject": subject, "predicate": fact["predicate"],
                              "object": obj}
                decision = await self._dedup_decide(chat_id, dedup_fact, sentence, vector)
                if decision["action"] == "noop":
                    await self.db.confirm_graph_fact(
                        decision["old_id"], int(time.time()),
                        (hot.get("limits.graph_dedup_weight_bonus", settings.GRAPH_DEDUP_WEIGHT_BONUS) or 0))
                    deduped += 1
                    logger.info("graphrag dedup: noop | chat_id=%s | fact_id=%s",
                                chat_id, decision["old_id"])
                    continue
                status = ("unconfirmed" if decision["action"] == "supersede"
                          else "confirmed")
                # Epic 60 (66.4, T-482): квота прямых фактов на человека —
                # сверх лимита вытесняется самый лёгкий и старый.
                if hot.get("flags.graph_user_quota_enabled", settings.GRAPH_USER_QUOTA_ENABLED) and target_user and \
                        (hot.get("limits.graph_facts_per_user_quota", settings.GRAPH_FACTS_PER_USER_QUOTA) or 0) > 0:
                    try:
                        await self._enforce_user_quota(chat_id, target_user)
                    except Exception:
                        logger.warning(
                            "graphrag quota: eviction failed — insert proceeds "
                            "| chat_id=%s", chat_id, exc_info=True)
                sid = await self.db.upsert_node(
                    chat_id, subject, "fact", origin=source_type, expires_at=expiry)
                oid = await self.db.upsert_node(
                    chat_id, obj, "fact", origin=source_type, expires_at=expiry)
                await self.db.upsert_edge(
                    sid, oid, fact["predicate"], origin=source_type, expires_at=expiry)
                fact_id = await self.db.insert_graph_fact(
                    chat_id, sentence, source_type, expiry, target_user=target_user,
                    status=status, weight=weight,
                    supersedes=(decision["old_id"]
                                if decision["action"] == "supersede" else None))
                if decision["action"] == "supersede":
                    # свежий побеждает = инвалидация (НЕ перезапись); журнал
                    # «что во что» — обратимость антиотравления (64.2)
                    await self.db.invalidate_graph_fact(
                        decision["old_id"], int(time.time()))
                    await self.db.log_fact_compression(
                        chat_id, fact_id, decision["old_text"], sentence,
                        "supersede")
                    superseded += 1
                if self._vec_available:
                    await self._save_graph_fact_embedding(
                        fact_id, chat_id, sentence, source_type, expiry,
                        vector=vector)
                saved += 1
            except Exception as exc:
                # Epic 47 (D188, 56.5): один БД-сбой не роняет батч (per-fact)
                skipped += 1
                logger.warning("graphrag memorize: fact #%d save skipped | error=%s",
                               i, exc)
                continue
        logger.info(
            "graphrag memorize: saved=%d skipped=%d deduped=%d superseded=%d "
            "| chat_id=%s | source=%s",
            saved, skipped, deduped, superseded, chat_id, source_type)

    def _canon_fact_name(self, name: str) -> str:
        """66.9 (T-487): имя → канон-алиас (обратная карта). Без aliases —
        имя как есть (уже normalize в _validate_fact)."""
        if self.aliases is None:
            return name
        return self.aliases.canon_name(name)

    async def _participant_display_canons(self, chat_id: int) -> dict[str, str]:
        """C4/T-795 (spec §3.C4.1-2): «карта дисплеев» чата для привязки
        фактов — участники за limits.chat_map_participants_hours (тот же
        db.get_active_participants, что C2-карта). Ключи (casefold):
        последний автор-ник участника из карты (MAX(author_name) — то, что
        LLM видел в тексте) и его display (resolve-результат: алиас при
        наличии, иначе сам ник); значение — канон участника (resolve-результат
        через алиасы). Совпадение канона с самим собой не пишется (no-op).
        Без aliases канон == display — мапа пуста (поведение до раунда 8)."""
        hours = int(hot.get("limits.chat_map_participants_hours",
                            settings.CHAT_MAP_PARTICIPANTS_HOURS) or 24)
        cap = int(hot.get("limits.chat_map_participants_cap",
                          settings.CHAT_MAP_PARTICIPANTS_CAP) or 0) or 150
        since = int(time.time()) - hours * 3600
        rows = await self.db.get_active_participants(chat_id, since, cap)
        mapping: dict[str, str] = {}
        for row in rows:
            uid = row["user_id"]
            raw = str(row["author_name"] or "").strip()
            if uid in (None, 0) or not raw:
                continue
            if self.aliases is not None:
                canon = self.aliases.resolve(int(uid), raw, None)
            else:
                canon = raw
            canon_key = canon.casefold()
            for key in {raw.casefold(), canon_key}:
                if key and key != canon_key:
                    mapping[key] = canon
        return mapping

    async def _enforce_user_quota(self, chat_id: int, target_user: str) -> None:
        """66.4 (T-482): live-фактов юзера >= квоты → удалить факт с
        минимальным score weight/(age_days+1) (жертвуем самым лёгким и старым);
        журнал — graph_fact_compressions (reason='quota'). Защищённые факты не
        кандидаты (65.10); если кандидатов нет (все защищены) — вытеснения
        нет, квота мягко превышается один раз."""
        quota = (hot.get("limits.graph_facts_per_user_quota", settings.GRAPH_FACTS_PER_USER_QUOTA) or 0)
        now = int(time.time())
        victim = await self.db.get_quota_victim(chat_id, target_user, quota, now)
        if victim is None:
            return
        await self.db.delete_graph_fact(victim["id"])
        await self.db.log_fact_compression(
            chat_id, victim["id"], victim["fact"], None, "quota")
        logger.info(
            "graphrag quota: evicted fact_id=%s | chat_id=%s | user=%s | quota=%d",
            victim["id"], chat_id, target_user, quota)

    async def _dedup_decide(self, chat_id: int, fact: dict, sentence: str,
                            vector) -> dict:
        """64.1 (T-462): exact-дубль ('s p o' / 's p o (ctx)') → noop; KNN k=3
        (та же пара сущностей): cosine = 1 − distance; ≥ HIGH (0.95) → noop;
        [LOW (0.85), HIGH) → supersede; < LOW → add. Вектора нет → только
        exact (честная деградация R3-стиля). НЕ бросает: любая ошибка →
        WARNING → add (64.1.5). Epic 60 (65.10/66.10, T-488): защищённый
        факт дедуп НЕ трогает (ни noop-подтверждение, ни supersede-
        инвалидация) — кандидат пропускается."""
        try:
            if not hot.get("flags.graph_dedup_enabled", settings.GRAPH_DEDUP_ENABLED):
                return {"action": "add", "old_id": None, "old_text": None}
            key = f"{fact['subject']} {fact['predicate']} {fact['object']}"
            exact = await self.db.find_graph_fact_exact(
                chat_id, key, int(time.time()))
            if exact is not None and \
                    not await self.db.is_fact_protected(chat_id, exact["fact"]):
                return {"action": "noop", "old_id": exact["id"],
                        "old_text": exact["fact"]}
            if vector is None or not self._vec_available:
                return {"action": "add", "old_id": None, "old_text": None}
            near = await self._dedup_knn(chat_id, vector)
            rows = await self.db.get_graph_fact_rows(
                [row["fact_id"] for row in near])
            by_id = {row["id"]: row for row in rows}
            for row in near:
                candidate = by_id.get(row["fact_id"])
                if candidate is None:
                    continue
                text = candidate["fact"] or ""
                if fact["subject"] not in text or fact["object"] not in text:
                    continue                    # не та пара сущностей
                # 65.10/66.10: защищённый факт не инвалидируется/не
                # подтверждается автоматически — пропускаем кандидата.
                if await self.db.is_fact_protected(chat_id, text):
                    continue
                cosine = 1.0 - row["distance"]
                if cosine >= (hot.get("limits.graph_dedup_similarity_high", settings.GRAPH_DEDUP_SIMILARITY_HIGH) or 0):
                    return {"action": "noop", "old_id": candidate["id"],
                            "old_text": text}
                if cosine >= (hot.get("limits.graph_dedup_similarity_low", settings.GRAPH_DEDUP_SIMILARITY_LOW) or 0):
                    return {"action": "supersede", "old_id": candidate["id"],
                            "old_text": text}
                return {"action": "add", "old_id": None, "old_text": None}
            return {"action": "add", "old_id": None, "old_text": None}
        except Exception:
            logger.warning(
                "graphrag dedup: check failed — fact added as before (64.1.5)",
                exc_info=True,
            )
            return {"action": "add", "old_id": None, "old_text": None}

    async def _dedup_knn(self, chat_id: int, vector: list[float]) -> list:
        """64.1: KNN k=3 по graph_facts_vec (chat-фильтр + TTL). БЕЗ фильтров
        origin/status — unconfirmed участвует как кандидат подтверждения."""
        now = int(time.time())
        cursor = await self.db.db.execute(
            "SELECT fact_id, chat_id, expires_at, distance FROM graph_facts_vec "
            "WHERE embedding MATCH ? AND k = ?",
            (json.dumps(vector), 3))
        return [
            row for row in await cursor.fetchall()
            if row["chat_id"] == chat_id
            and (row["expires_at"] is None or row["expires_at"] > now)
        ]

    async def _save_graph_fact_embedding(self, fact_id, chat_id, fact, origin,
                                         expires_at, vector=None) -> None:
        try:
            if vector is None:
                vectors = await self._embed([fact])          # ретраи 55.8 + кэш 64.4
                vector = vectors[0]
            await self._insert_graph_vec_row(fact_id, chat_id, fact, origin,
                                             expires_at, vector)
            await self.db.db.commit()
        except Exception:
            logger.warning(
                "[graphrag] embed failed — fact saved text-only | fact_id=%d",
                fact_id, exc_info=True)

    # ── Раунд 4 (T-713, FR-D2, spec 3.4.3): «запомни» — user_memory ──

    async def remember_user_fact(self, chat_id: int, fact: str, *,
                                 target_user: str | None = None,
                                 ttl_days: int | None = 365) -> str:
        """Память-команда «запомни»: факт ВЕРБАТИМ (без LLM-экстракции —
        memorize_facts НЕ используется) → graph_facts origin='user_memory',
        weight=1.0, status='confirmed'. target_user — канон-имя автора
        (юзер) или None (админ/модер → факт чата). ttl_days: 0/None → вечно
        (expires_at NULL), иначе now + ttl_days*86400 (множитель (0.5+weight)
        НЕ применяется — TTL задан прямо). Exact-дедуп по
        (chat_id, origin, target_user IS NOT DISTINCT FROM, lower(fact)),
        живые строки → «duplicate» (повторно НЕ вставляем). FTS-строка —
        внутри insert_graph_fact; vec-строка — fail-open при embed-сбое
        (WARNING, FTS жив; иначе добирает ленивый backfill на старте).
        user_memory НЕ создаёт nodes/edges (прямой INSERT, не граф-триплет).
        Возвращает "saved" | "duplicate"."""
        fact = " ".join(str(fact or "").split())
        if not fact:
            return "duplicate"                  # пусто — noop (parse уже отсеял)
        expiry = (None if ttl_days in (None, 0)
                  else int(time.time() + int(ttl_days) * 86400))
        now = int(time.time())
        try:
            # Exact-дедуп (3.4.3/FR-D2): тот же scope (target_user IS NOT
            # DISTINCT FROM — NULL-факт чата общий) и тот же текст. lower()
            # в SQLite не фолдит кириллицу → сравнение casefold в Python
            # (факт НЕ должен задваиваться при разнице регистра).
            cursor = await self.db.db.execute(
                "SELECT fact FROM graph_facts "
                "WHERE chat_id = ? AND origin = 'user_memory' "
                "AND (target_user IS ? OR target_user IS NULL) "
                "AND (expires_at IS NULL OR expires_at > ?) LIMIT 100",
                (chat_id, target_user, now))
            needle = fact.casefold()
            for row in await cursor.fetchall():
                if str(row["fact"] or "").casefold() == needle:
                    return "duplicate"
            fact_id = await self.db.insert_graph_fact(
                chat_id, fact, "user_memory", expiry,
                target_user=target_user, weight=1.0)
            if self._vec_available:
                await self._save_graph_fact_embedding(
                    fact_id, chat_id, fact, "user_memory", expiry)
            logger.info(
                "[user_memory] remember | chat_id=%s | target_user=%r | "
                "ttl_days=%s | fact_id=%d", chat_id, target_user, ttl_days,
                fact_id)
            return "saved"
        except Exception:
            logger.warning(
                "[user_memory] remember failed — fail-open | chat_id=%s",
                chat_id, exc_info=True)
            raise

    # ── GraphRAG v2: гибридный RAG (Epic 46, Section 55.6) ────────

    async def get_rag_context(self, chat_id: int, query: str, *,
                              sort_by_timestamp: bool = False,
                              include_direct_reply: bool = False) -> str:
        """Гибридный RAG (55.6): векторный поиск по graph_facts_vec (KNN) →
        FTS5-фолбек (graph_facts_fts). Ленивый TTL (D175). Возвращает КАНОН-XML
        или "". НИКОГДА не бросает (любая ошибка → WARNING → "").
        Epic 50 (58.8, D206): sort_by_timestamp=True (ТОЛЬКО DirectChat) —
        стабильная сортировка фактов по created_at ASC (таймлайн
        <RAG_Memory>); include_direct_reply=True — origin='bot_direct_reply'
        участвует (default False: direct-флуд не подмешивается в чужие
        пайплайны)."""
        if not hot.get("flags.graph_rag_enabled", settings.GRAPH_RAG_ENABLED):
            return ""
        try:
            facts = await self._search_graph_facts(
                chat_id, str(query or ""), (hot.get("limits.graph_rag_facts_limit", settings.GRAPH_RAG_FACTS_LIMIT) or 0),
                include_direct_reply=include_direct_reply)
        except Exception:
            logger.warning("graphrag RAG: search failed — empty context | chat_id=%s",
                           chat_id, exc_info=True)
            return ""
        if sort_by_timestamp:
            facts = sorted(facts, key=lambda f: f[2] or 0)   # стабильная сортировка, ASC
        # Раунд 4 (T-724, FR-F1): рендер 3-кортежей (origin, fact, created_at) —
        # дата-префикс '[%Y-%m-%d] ' в контексте («что было N-числа» через RAG).
        context = build_rag_context(facts)
        if context and len(context) > (hot.get("limits.graph_rag_context_max_chars", settings.GRAPH_RAG_CONTEXT_MAX_CHARS) or 0):
            logger.warning("graphrag RAG: context truncated to %d chars | chat_id=%s",
                           (hot.get("limits.graph_rag_context_max_chars", settings.GRAPH_RAG_CONTEXT_MAX_CHARS) or 0), chat_id)
            context = context[:(hot.get("limits.graph_rag_context_max_chars", settings.GRAPH_RAG_CONTEXT_MAX_CHARS) or 0)]
        if context:
            logger.info("graphrag RAG: facts=%d | chat_id=%s | chars=%d",
                        len(facts), chat_id, len(context))
        return context

    # ── RAG-факты direct-пути (Раунд 8: F1/T-807, F2/T-808, F4/T-810) ──

    async def get_rag_facts(self, chat_id: int, query: str, *,
                            include_direct_reply: bool = False) -> list:
        """F1/T-807 (spec §3.F1): кандидаты RAG direct-пути как список
        3-кортежей (origin, fact, created_at) в порядке РЕЛЕВАНТНОСТИ —
        KNN: rel = cosine × w_eff + MMR (_knn_graph_facts); FTS-фолбек:
        w_eff DESC. Хронологическая сортировка sort_by_timestamp НЕ
        применяется (она осталась только у get_rag_context для
        search/factcheck/скриптов — те пути не тронуты; даты остаются
        ВНУТРИ каждого факта для рендера). Никогда не бросает: выключенный
        RAG/любая ошибка → [] (WARNING)."""
        if not hot.get("flags.graph_rag_enabled", settings.GRAPH_RAG_ENABLED):
            return []
        try:
            return await self._search_graph_facts(
                chat_id, str(query or ""),
                (hot.get("limits.graph_rag_facts_limit",
                         settings.GRAPH_RAG_FACTS_LIMIT) or 0),
                include_direct_reply=include_direct_reply)
        except Exception:
            logger.warning(
                "graphrag RAG: facts search failed — empty list | chat_id=%s",
                chat_id, exc_info=True)
            return []

    async def rerank_rag_facts(self, query: str, facts: list) -> list:
        """F4/T-810 (spec §3.F4, образец search_service._rerank_results Epic 65):
        LLM-фильтр кандидатов direct-RAG после F1/F2, ПЕРЕД рендером.
        Кандидаты сериализуются нумерованным списком '1. [{label}] {date}
        {text}' (формат F3); ответ парсится regex «\\d+»; выжившие факты
        сохраняют исходный rel-порядок, остальные отбрасываются. Fail-open:
        LLM-ошибка/пустой/кривой ответ → исходный список (WARNING, NFR-6).
        Вызывается ТОЛЬКО при flags.chat_rag_rerank_enabled=True (проверку
        делает direct-путь ДО сериализации — off → 0 лишних LLM-вызовов)."""
        if not facts:
            return facts
        candidates = "\n".join(
            f"{i}. {_format_origin_labeled_line(item)}"
            for i, item in enumerate(facts, 1))
        try:
            raw = await self.llm.generate([
                {"role": "system", "content": _CHAT_RAG_RERANK_SYSTEM_PROMPT},
                {"role": "user", "content": (
                    f"<query>{escape_xml_text(str(query or ''))}</query>\n\n"
                    f"<candidates>\n{candidates}\n</candidates>")},
            ])
        except Exception as exc:
            logger.warning(
                "graphrag RAG: chat rerank failed — original facts | error=%s",
                exc)
            return facts
        picked = {int(n) for n in re.findall(r"\d+", str(raw or ""))
                  if 1 <= int(n) <= len(facts)}
        if not picked:
            logger.info(
                "graphrag RAG: chat rerank parsed no numbers — original facts")
            return facts
        logger.info("graphrag RAG: chat rerank OK | %d -> %d facts",
                    len(facts), len(picked))
        return [item for i, item in enumerate(facts, 1) if i in picked]

    async def _search_graph_facts(self, chat_id, query, limit,
                                  include_direct_reply=False) -> list:
        """[(origin, fact, created_at), ...]. Vec-путь: _ensure_vec_retry (55.8)
        → KNN (66.6: int8-coarse → float-реранк; 66.8: MMR); фейл embed/vec →
        FTS-фолбек. Epic 50 (58.8, D206): default — фильтр origin=
        'bot_direct_reply'. Epic 60 (66.3/66.5): FTS-путь — top-2×limit по
        rank → пересортировка по w_eff DESC → touch (продление жизни)."""
        now = int(time.time())
        if await self._ensure_vec_retry():
            try:
                vectors = await self._embed([query])
                if vectors and vectors[0]:
                    rows = await self._knn_graph_facts(
                        chat_id, vectors[0], limit, include_direct_reply=include_direct_reply)
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
        rows = await self.db.search_graph_facts_fts(
            chat_id, match_query, limit * 2, now, include_direct_reply=include_direct_reply)
        if not rows:
            return []
        # 66.3 (T-481): время-взвешивание в Python (SQL-ранг не меняем);
        # стабильная сортировка — равные w_eff сохраняют FTS-порядок.
        ranked = sorted(
            rows,
            key=lambda r: _effective_weight(r["weight"], r["last_confirmed_at"], now),
            reverse=True)
        kept = ranked[:limit]
        if kept and hot.get("flags.graph_fact_touch_enabled", settings.GRAPH_FACT_TOUCH_ENABLED):
            try:
                await self.db.touch_graph_facts(
                    [r["id"] for r in kept], (hot.get("limits.graph_fact_touch_extend_days", settings.GRAPH_FACT_TOUCH_EXTEND_DAYS) or 0),
                    (hot.get("limits.chat_direct_reply_ttl_days", settings.CHAT_DIRECT_REPLY_TTL_DAYS) or 0), (hot.get("limits.graph_fact_ttl_days", settings.GRAPH_FACT_TTL_DAYS) or 0),
                    now)
            except Exception:
                logger.warning("graphrag RAG: touch failed | chat_id=%s",
                               chat_id, exc_info=True)
        # Фаза 2 (T-759): рендер ts = COALESCE(message_timestamp, created_at) —
        # импортированные факты показывают дату сообщения-источника.
        return [(row["origin"], row["fact"], row["rag_ts"]) for row in kept]

    async def _knn_graph_facts(self, chat_id, vector, limit,
                               include_direct_reply=False) -> list:
        """KNN-путь GraphRAG (55.6) + Epic 60:
        - 66.6 (T-484): int8-coarse (k = fetch_k×4) → реранк точной cosine по
          float-колонке → top-fetch_k; float-only — точный MATCH (как раньше);
        - 66.8 (T-486): greedy MMR (λ, fetch_k) — диверсификация по float;
        - 66.1/66.3 (T-479/T-481): rel = cosine × w_eff (вес + time-decay);
        - 66.5 (T-483): touch — RAG-hit продлевает expires_at (батчем)."""
        now = int(time.time())
        fetch_k = (max(limit, (hot.get("limits.graph_mmr_fetch_k", settings.GRAPH_MMR_FETCH_K) or 0))
                   if hot.get("flags.graph_mmr_enabled", settings.GRAPH_MMR_ENABLED) else limit * 2)
        ranked = await self._vec_candidates(
            chat_id, vector, fetch_k, include_direct_reply, now)
        ranked = ranked[:fetch_k]
        if not ranked:
            return []
        records = await self.db.get_graph_fact_records(
            [fid for fid, _, _ in ranked], status="confirmed")
        by_id = {r["id"]: r for r in records}
        sims: list = []
        for fid, cosine, vec in ranked:
            row = by_id.get(fid)
            if row is None:
                continue
            w_eff = _effective_weight(row["weight"], row["last_confirmed_at"], now)
            sims.append((fid, cosine * w_eff, vec))
        if not sims:
            return []
        if hot.get("flags.graph_mmr_enabled", settings.GRAPH_MMR_ENABLED):
            if any(vec is None for _, _, vec in sims):
                sims = await self._attach_vectors(sims)
            chosen = _mmr_select(sims, limit, (hot.get("limits.graph_mmr_lambda", settings.GRAPH_MMR_LAMBDA) or 0))
        else:
            sims.sort(key=lambda s: s[1], reverse=True)
            chosen = [s[0] for s in sims[:limit]]
        if chosen and hot.get("flags.graph_fact_touch_enabled", settings.GRAPH_FACT_TOUCH_ENABLED):
            try:
                await self.db.touch_graph_facts(
                    chosen, (hot.get("limits.graph_fact_touch_extend_days", settings.GRAPH_FACT_TOUCH_EXTEND_DAYS) or 0),
                    (hot.get("limits.chat_direct_reply_ttl_days", settings.CHAT_DIRECT_REPLY_TTL_DAYS) or 0), (hot.get("limits.graph_fact_ttl_days", settings.GRAPH_FACT_TTL_DAYS) or 0),
                    now)
            except Exception:
                logger.warning("graphrag RAG: touch failed | chat_id=%s",
                               chat_id, exc_info=True)
        # Фаза 2 (T-759): KNN-путь — ts = message_timestamp or created_at
        # (импортированные факты: дата сообщения, не дата импорта).
        return [(by_id[f]["origin"], by_id[f]["fact"],
                 by_id[f]["message_timestamp"] or by_id[f]["created_at"])
                for f in chosen]

    async def _vec_candidates(self, chat_id, vector, fetch_k,
                              include_direct_reply, now) -> list:
        """[(fact_id, cosine, float_vector|None), ...] по убыванию cosine.
        int8-путь: грубый KNN → реранк по float (66.6); фейл int8 → float-MATCH
        (точная дистанция). Float-only: точный MATCH k=fetch_k×2."""
        if self._vec_int8:
            rows = await self._vec_int8_rows(
                chat_id, vector, fetch_k * 4, include_direct_reply, now)
            if rows is not None:
                return await self._rerank_by_float(vector, rows)
        rows = await self._vec_float_rows(
            chat_id, vector, fetch_k * 2, include_direct_reply, now)
        return [(row["fact_id"], 1.0 - row["distance"], None) for row in rows]

    async def _vec_int8_rows(self, chat_id, vector, k, include_direct_reply, now):
        """66.6: грубый KNN по int8-колонке (query квантизуется в SQL).
        Ошибка → None (float-fallback честная деградация)."""
        try:
            cursor = await self.db.db.execute(
                "SELECT fact_id, chat_id, origin, expires_at FROM graph_facts_vec "
                "WHERE embedding_i8 MATCH vec_quantize_int8(?, 'unit') AND k = ?",
                (json.dumps(vector), k))
            return self._filter_vec_rows(
                await cursor.fetchall(), chat_id, include_direct_reply, now)
        except Exception:
            logger.warning(
                "graphrag RAG: int8 KNN failed — float path | chat_id=%s",
                chat_id, exc_info=True)
            return None

    async def _vec_float_rows(self, chat_id, vector, k, include_direct_reply, now) -> list:
        cursor = await self.db.db.execute(
            "SELECT fact_id, chat_id, origin, expires_at, distance "
            "FROM graph_facts_vec WHERE embedding MATCH ? AND k = ?",
            (json.dumps(vector), k))
        return self._filter_vec_rows(
            await cursor.fetchall(), chat_id, include_direct_reply, now)

    @staticmethod
    def _filter_vec_rows(rows, chat_id, include_direct_reply, now) -> list:
        return [
            row for row in rows
            if row["chat_id"] == chat_id
            and (include_direct_reply or row["origin"] != "bot_direct_reply")
            and (row["expires_at"] is None or row["expires_at"] > now)
        ]

    async def _rerank_by_float(self, query: list[float], candidates: list) -> list:
        """66.6: реранк кандидатов точной cosine по float-канону (векторы
        читаются из vec-таблицы как float32-BLOB; фейл чтения → кандидат
        пропускается)."""
        ids = [row["fact_id"] for row in candidates]
        if not ids:
            return []
        placeholders = ",".join("?" for _ in ids)
        cursor = await self.db.db.execute(
            f"SELECT rowid AS fact_id, embedding FROM graph_facts_vec "
            f"WHERE rowid IN ({placeholders})", ids)
        vecs: dict[int, list[float]] = {}
        for row in await cursor.fetchall():
            blob = row["embedding"]
            try:
                if isinstance(blob, str):
                    vec = json.loads(blob)
                else:
                    vec = list(struct.unpack(
                        f"<{len(bytes(blob)) // 4}f", bytes(blob)))
            except Exception:
                continue
            vecs[row["fact_id"]] = vec
        ranked = []
        for row in candidates:
            vec = vecs.get(row["fact_id"])
            if vec is None:
                continue
            ranked.append((row["fact_id"], _cosine(query, vec), vec))
        ranked.sort(key=lambda item: item[1], reverse=True)
        return ranked

    async def _attach_vectors(self, sims: list) -> list:
        """66.8: float-векторы кандидатов для pairwise-MMR (float-путь отдаёт
        их лениво — один батч-SELECT)."""
        ids = [fid for fid, _, vec in sims if vec is None]
        if not ids:
            return sims
        placeholders = ",".join("?" for _ in ids)
        cursor = await self.db.db.execute(
            f"SELECT rowid AS fact_id, embedding FROM graph_facts_vec "
            f"WHERE rowid IN ({placeholders})", ids)
        vecs: dict[int, list[float]] = {}
        for row in await cursor.fetchall():
            blob = row["embedding"]
            try:
                if isinstance(blob, str):
                    vec = json.loads(blob)
                else:
                    vec = list(struct.unpack(
                        f"<{len(bytes(blob)) // 4}f", bytes(blob)))
                vecs[row["fact_id"]] = vec
            except Exception:
                continue
        return [
            (fid, rel, vecs.get(fid) if vec is None else vec)
            for fid, rel, vec in sims
        ]

    # ── GraphRAG lookup for /summary (R26-3, D71) ───────────────

    async def backfill_direct_reply_ttl(self) -> int:
        """FR-C2 (T-697): идемпотентный backfill существующих NULL-фактов:
        origin='bot_direct_reply' AND expires_at IS NULL →
        expires_at = min(created_at + ttl*86400, now) при ttl>0 (0/None →
        no-op — вечные по явному выбору). Повторный старт безвреден (NULL-строк
        больше нет). Лог '[graphrag] bot_direct_reply backfill | rows=%d'."""
        ttl_days = (hot.get("limits.chat_direct_reply_ttl_days",
                            settings.CHAT_DIRECT_REPLY_TTL_DAYS) or 0)
        if not ttl_days or ttl_days <= 0:
            return 0
        try:
            now = int(time.time())
            cursor = await self.db.db.execute(
                "UPDATE graph_facts SET expires_at = "
                "MIN(created_at + ?, ?) "
                "WHERE origin = 'bot_direct_reply' AND expires_at IS NULL",
                (int(ttl_days) * 86400, now))
            rows = cursor.rowcount
            if rows:
                await self.db.db.commit()
                logger.info("[graphrag] bot_direct_reply backfill | rows=%d",
                            rows)
            return rows
        except Exception:
            logger.warning(
                "[graphrag] bot_direct_reply backfill failed", exc_info=True)
            return 0

    async def get_graph_facts(
        self, chat_id: int, rows: list, keywords: list[str]
    ) -> list[str]:
        """R26-3: детерминированный graph-поиск по сущностям окна L1 → строки справок.
        Epic 60 (66.3, T-481): time-decay рёбер — w_eff = weight ×
        0.5^(Δдней/half_life) от last_updated (пересчёт в Python после выборки
        top-2×limit, пересортировка по w_eff DESC; SQL не меняем)."""
        if not hot.get("flags.graph_rag_enabled", settings.GRAPH_RAG_ENABLED):
            return []
        try:
            user_names = [
                _normalize_name(r["author_name"])
                for r in rows
                if (r["author_name"] or "").strip()
            ]
            topic_kws = [kw.lower() for kw in keywords[:2]]
            entity_ids = await self.db.match_nodes(chat_id, user_names, topic_kws)
            limit = (hot.get("limits.graph_top_edges_limit", settings.GRAPH_TOP_EDGES_LIMIT) or 0)
            if entity_ids:
                edges = await self.db.get_top_edges(
                    chat_id, entity_ids, limit * 2
                )
                if not edges:                       # сущности есть, но рёбер у них нет
                    edges = await self.db.get_top_edges_all(
                        chat_id, limit * 2
                    )
            else:                                   # окно не сматчилось ни с одним узлом (холодный граф)
                edges = await self.db.get_top_edges_all(
                    chat_id, limit * 2
                )
            now = int(time.time())
            edges = sorted(
                edges,
                key=lambda e: self._edge_effective_weight(e, now),
                reverse=True)[:limit]
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
    def _edge_effective_weight(row, now: int) -> float:
        """66.3: эффективный вес ребра — weight × decay от last_updated
        ('YYYY-MM-DD HH:MM:SS' UTC); кривой формат → без затухания."""
        if not hot.get("flags.graph_time_decay_enabled", settings.GRAPH_TIME_DECAY_ENABLED):
            return float(row["weight"] or 1)
        try:
            ts = calendar.timegm(time.strptime(
                str(row["last_updated"]), "%Y-%m-%d %H:%M:%S"))
        except (ValueError, TypeError, KeyError):
            ts = now
        days = max(0.0, (now - ts) / 86400.0)
        # N2/N4: half_life в знаменателе — 0/NULL → max(1) (без ZeroDivision);
        # floor — or 0 по смыслу.
        half_life = max(1.0, hot.get(
            "limits.graph_time_decay_half_life_days",
            settings.GRAPH_TIME_DECAY_HALF_LIFE_DAYS) or 1.0)
        w_eff = float(row["weight"] or 1) * (0.5 ** (days / half_life))
        return max(hot.get("limits.graph_time_decay_floor",
                           settings.GRAPH_TIME_DECAY_FLOOR) or 0.0, w_eff)

    @staticmethod
    def _format_graph_fact(row) -> str:
        """One line per edge: [Историческая справка: A (relation) B] (35.5)."""
        return (
            f"[Историческая справка: {row['source_name']} "
            f"({row['relation_type']}) {row['target_name']}]"
        )

    # ── L3 compression + retention (A5: called only under generator lock) ──

    async def compress_and_purge(self, chat_id: int) -> None:
        """L3-компрессия + retention (крон 4×/день + ручной /summary).
        Фаза 2 (T-756, G1): memory.infinite_retention ON → extract-only ветка
        (_compress_purge_extract_only): граф пополняется nodes/edges по
        пачкам старых сообщений БЕЗ сжатия, БЕЗ удаления сырья и БЕЗ записи
        smart_archive; импортированные строки (import_key IS NOT NULL) из
        extract исключаются (их графом пополняет Graph-воркер). OFF — ровно
        текущий код (сжатие → smart_archive+extract → DELETE сырья)."""
        if hot.get("memory.infinite_retention", settings.INFINITE_RETENTION):
            await self._compress_purge_extract_only(chat_id)
            return
        cutoff = int(time.time()) - (hot.get("limits.full_memory_retention_days", settings.FULL_MEMORY_RETENTION_DAYS) or 0) * 86400
        batch_size = (hot.get("limits.summary_compress_batch", settings.SUMMARY_COMPRESS_BATCH) or 0)
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
                if hot.get("flags.graph_rag_enabled", settings.GRAPH_RAG_ENABLED):                       # D69: False → ровно старое поведение
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

    async def _compress_purge_extract_only(self, chat_id: int) -> None:
        """G1 (T-756): extract-only ветка при memory.infinite_retention ON —
        сырьё живёт вечно (L1/FTS по всей истории), граф пополняется
        nodes/edges из пачек старых сообщений. smart_archive НЕ пишется,
        пачки НЕ удаляются, _purge_archive НЕ вызывается (гейт G2),
        purge-гейты G3-G5 живут в db-слое. Импортированные строки
        (import_key IS NOT NULL) в выборку не попадают — их графом пополняет
        только Graph-воркер истории (history_processed), параллельная
        крон-LLM-экстракция по ним исключена (дубли/двойные деньги).

        Маркер обработанности (fix B-раунда): выборка берёт только
        history_processed = 0 (exclude_processed), после успешной экстракции
        окна строки помечаются history_processed=1
        (db.mark_smart_messages_processed — только live, import_key IS NULL)
        — иначе live-строки старше cutoff пере-экстрактились бы каждым
        кроном 4×/день вечно (инфляция весов рёбер). С Graph-воркером
        колонка общая, НО наборы строк дизъюнктны: воркер берёт/помечает
        import_key IS NOT NULL, extract-only — import_key IS NULL.

        No-op при flags.graph_rag_enabled OFF (fix B-раунда): extract_enabled
        вычислен ниже → ранний выход БЕЗ маркировки history_processed — иначе
        при ≥batch_size необработанных live-строк старше cutoff был бы
        бесконечный busy-loop (строки не помечаются/не удаляются, выход
        только по len(ids) < batch_size). Строки остаются непомеченными —
        при включении graph-флага экстракция возобновится с той же выборки
        (exclude_processed=True отдаст их снова). Без экстракции маркер НЕ
        ставится."""
        cutoff = int(time.time()) - (hot.get("limits.full_memory_retention_days", settings.FULL_MEMORY_RETENTION_DAYS) or 0) * 86400
        batch_size = (hot.get("limits.summary_compress_batch", settings.SUMMARY_COMPRESS_BATCH) or 0)
        extract_enabled = hot.get("flags.graph_rag_enabled", settings.GRAPH_RAG_ENABLED)
        if not extract_enabled:
            logger.debug(
                "SmartModule L3 (retention ON): extract-only no-op — "
                "flags.graph_rag_enabled OFF, строки не помечаются (экстракция "
                "возобновится при включении флага) | chat_id=%s",
                chat_id,
            )
            return
        processed = 0
        while True:
            batch = await self.db.get_smart_raw(
                chat_id, cutoff, batch_size, exclude_imported=True,
                exclude_processed=True)
            if not batch:
                break
            ids = [row["id"] for row in batch]
            try:
                await self._extract_and_save_graph(chat_id, batch)
            except Exception:
                logger.exception(
                    "SmartModule L3 (retention ON): extract failed — batch kept, "
                    "pipeline continues | chat_id=%s",
                    chat_id,
                )
                break
            # успешная экстракция окна → маркер (повторный крон не
            # пере-экстрактит; новые строки после маркера — экстрактятся)
            await self.db.mark_smart_messages_processed(chat_id, ids)
            processed += len(ids)
            if len(ids) < batch_size:
                break
        if processed:
            logger.info(
                "SmartModule L3 (retention ON): extract-only %d messages kept "
                "(no compression) | chat_id=%s", processed, chat_id
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
            # Epic 60 (66.9, T-487): user-сущности — канон-имена по алиасам
            # (карточки /persona и связи графа агрегируются по одному имени).
            subject = _normalize_name(triplet["subject"])
            obj = _normalize_name(triplet["object"])
            if triplet["subject_type"] == "user":
                subject = self._canon_fact_name(subject)
            if triplet["object_type"] == "user":
                obj = self._canon_fact_name(obj)
            sid = await self.db.upsert_node(
                chat_id, subject, triplet["subject_type"]
            )
            oid = await self.db.upsert_node(
                chat_id, obj, triplet["object_type"]
            )
            await self.db.upsert_edge(
                sid,
                oid,
                _normalize_name(triplet["predicate"]),
                weight_increment=(hot.get("limits.graph_edge_weight_increment", settings.GRAPH_EDGE_WEIGHT_INCREMENT) or 0),
            )
        logger.info("graph: triplets=%d | chat_id=%s", len(triplets), chat_id)

    async def _save_archive_embedding(self, chat_id: int, fact_id: int, fact: str) -> None:
        try:
            vectors = await self._embed([fact])          # кэш 64.4 + ретраи 55.8
            vector = vectors[0]
            if self._vec_int8:
                await self.db.db.execute(
                    "INSERT INTO smart_archive(rowid, fact_id, chat_id, "
                    "embedding, embedding_i8) VALUES (?, ?, ?, ?, "
                    "vec_quantize_int8(?, 'unit'))",
                    (fact_id, fact_id, chat_id, json.dumps(vector),
                     json.dumps(vector)))
            else:
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
        """G2 (T-756): memory.infinite_retention ON → skip (архивные факты не
        удаляются по ретенции; живут до OFF). OFF — ровно текущее поведение."""
        if hot.get("memory.infinite_retention", settings.INFINITE_RETENTION):
            return
        archive_cutoff = int(time.time()) - (hot.get("limits.archive_memory_retention_days", settings.ARCHIVE_MEMORY_RETENTION_DAYS) or 0) * 86400
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
