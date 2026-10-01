"""Раунд 10.27 (MCA Wave 2, `mca-05-episodes-stories`, ADR-1027-12) —
EpisodeService: модель Episode/Story, пайплайн сборки и фасад интеграции.

**Владелец** (D1): единственный владелец таблиц `mca_episodes`/`mca_stories`/
`mca_story_versions`/`mca_story_episode_links`/`mca_story_continuations`/
`mca_story_redirects`/`mca_story_legacy_links` (v21) и пайплайна сборки.
Все записи — через `write_transaction`/single-writer `mca-01`; чтение →
LLM → короткая запись разделены (MCA14-R3 — без долгой транзакции).
UI в БД не ходит (GEN-R21); `lore_worker`/dream/summary не трогаются —
EpisodeService читает уже сохранённые `smart_messages`, ничего не принимая
из Telegram, и не имеет пути отправки (§2 п.2).

**Инварианты модели** (D3, §9.1):
  * состояние истории `state ∈ {open, closed, uncertain}` и статус задания
    обработки (`task_status_ref`/`task_jobs.status`) — РАЗНЫЕ поля;
  * общая тема ≠ общая история (уникальность по `story_id`/canonical
    event-идентичности, не по `topic_key`);
  * две даты: `event_start/end` — по проверяемому времени исходных
    сообщений (mca-03), `discovered_at` — отдельно (A11);
  * неизвестный исход → «исход неизвестен» / `state='uncertain'`;
    финал не выдумывается;
  * ручные override-поля пайплайн никогда не затирает (A13);
  * конкурентная правка защищена CAS `expected_version`.

**Границы** (D13): UI — `mca-12` (Wave 5); публикация — вне фичи;
verbatim-episode ASAP-3 — другой механизм.

R17: в логах/событиях — id/коды/короткие R17-safe строки; сырой контекст
не дублируется (SourceRef вместо него).
"""
from __future__ import annotations

import asyncio
import dataclasses
import hashlib
import json
import logging
import re
import time
import uuid

from services import mca_gates
from services.database import (
    EPISODE_CONTINUATION_STATUSES,
    EPISODE_MAPPING_STATUSES,
    EPISODE_STORY_STATES,
    EPISODE_UNKNOWN_OUTCOME,
)

logger = logging.getLogger(__name__)

# ── версии пайплайна (участвуют в extraction_version записей) ───────────────
EPISODES_PIPELINE_VERSION = "mca05-episodes-1"
EXTRACTOR_VERSION = "episodes_extract-1"

# ── детерминированная сегментация (D4) — код-константы, Δ каталога = 0 ──────
SEGMENT_GAP_SECONDS = 1800          # жёсткий гэп времени (30 мин)
SEGMENT_SOFT_GAP_SECONDS = 600      # мягкий гэп для параллельных разговоров
REPLY_HORIZON_SECONDS = 6 * 3600    # reply-склейка в пределах горизонта
SEGMENT_MIN_MESSAGES = 1            # минимальный сегмент

# ── продолжения/сборка (D7) ─────────────────────────────────────────────────
CONTINUATION_MAX_CANDIDATES = 8     # bounded-кандидаты на batch
STORY_CLAIMS_MAX = 120              # кап утверждений истории
_STORY_EPS_CAP = 200                # кап эпизодов компонента (bounded)

_NEGATION_MARKERS = ("не ", "нет ", "никогда", "отмен", "перенес", "никак")
_WS_RE = re.compile(r"\s+")


class StaleUpdateError(RuntimeError):
    """CAS-конфликт: `expected_version` не совпал (stale update отклонён,
    не затирает — прецедент F0 persistItems/mca-04b staging, D9)."""


# ── стабильные ключи сообщений (mca-03 identity, D4) ────────────────────────

def message_key(row) -> str:
    """Стабильный ключ сообщения: `chat:tg:<tg_message_id>` при наличии
    (каноническая идентичность mca-03), иначе `chat:db:<id>`. Нормализованные
    строки сегмента уже несут `message_key` — возвращается как есть."""
    existing = _field(row, "message_key")
    if existing:
        return str(existing)
    chat = int(_field(row, "chat_id") or 0)
    tg = _field(row, "tg_message_id")
    if tg is not None:
        return f"{chat}:tg:{int(tg)}"
    mid = _field(row, "id")
    if mid is None:
        raise ValueError("message_key: нет ни tg_message_id, ни id")
    return f"{chat}:db:{int(mid)}"


def reply_key(row):
    """Ключ сообщения-родителя (reply), если он в той же выборке/чате."""
    chat = int(_field(row, "chat_id") or 0)
    rt = _field(row, "reply_to_tg_message_id")
    if rt is None:
        rt = _field(row, "reply_to_id")
    if rt is None:
        return None
    return f"{chat}:tg:{int(rt)}"


def segment_key(keys: list[str] | tuple[str, ...]) -> str:
    """Детерминированный natural key сегмента (дедуп overlap: те же
    сообщения → тот же ключ → INSERT OR IGNORE, без дублей)."""
    material = "\x1f".join(sorted({str(k) for k in keys or ()}))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]


# ── детерминированная сегментация (D4/§9.2 п.1–2; LLM порядок не меняет) ────

def segment_messages(messages: list[dict], *,
                     gap_seconds: int = SEGMENT_GAP_SECONDS,
                     soft_gap_seconds: int = SEGMENT_SOFT_GAP_SECONDS,
                     reply_horizon_seconds: int = REPLY_HORIZON_SECONDS,
                     ) -> list[list[dict]]:
    """Разбить сообщения на связные эпизоды-сегменты (детерминированное
    ядро: время + reply-граф + участники; тема — только LLM-суждение
    внутри/между сегментами).

    Правила границ (консервативные — ложный split приемлем, ложная склейка
    запрещена A12):
      1. сообщения сортируются по ``(timestamp, message_key)`` (stable keyset);
      2. reply-связь объединяет сообщения в один кластер (union-find),
         если временная дистанция ≤ ``reply_horizon_seconds``;
      3. граница между соседними сообщениями: гэп > ``gap_seconds`` И
         кластеры различны; либо гэп > ``soft_gap_seconds`` И автор
         нового сообщения не участвовал в текущем сегменте И кластеры
         различны (параллельные разговоры не смешиваются).
    Overlap батчей не создаёт дублей: дедуп по стабильному
    ``message_key``/`segment_key` (см. :func:`dedup_segments`).
    """
    rows = []
    seen: set[str] = set()
    for row in messages or ():
        key = str(_field(row, "message_key") or message_key(row))
        if key in seen:      # дедуп overlap по стабильному ключу
            continue
        seen.add(key)
        rows.append({
            "message_key": key,
            "timestamp": int(_field(row, "timestamp") or 0),
            "user_id": _normalize_id(_field(row, "user_id")),
            "reply_to_key": _field(row, "reply_to_key") or reply_key(row),
        })
    rows.sort(key=lambda r: (r["timestamp"], r["message_key"]))
    if not rows:
        return []
    index = {r["message_key"]: i for i, r in enumerate(rows)}
    parent = list(range(len(rows)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[max(ra, rb)] = min(ra, rb)

    for i, row in enumerate(rows):
        rtk = row.get("reply_to_key")
        if not rtk or rtk not in index:
            continue
        j = index[rtk]
        if abs(row["timestamp"] - rows[j]["timestamp"]) <= reply_horizon_seconds:
            union(i, j)

    segments: list[list[dict]] = []
    current: list[dict] = [rows[0]]
    participants = {rows[0]["user_id"]} if rows[0]["user_id"] is not None \
        else set()
    for prev, row in zip(rows, rows[1:]):
        gap = row["timestamp"] - prev["timestamp"]
        same_cluster = find(index[prev["message_key"]]) == \
            find(index[row["message_key"]])
        if not same_cluster and (gap > gap_seconds or (
                gap > soft_gap_seconds and row["user_id"] is not None
                and row["user_id"] not in participants)):
            segments.append(current)
            current = [row]
            participants = {row["user_id"]
                            if row["user_id"] is not None else None} - {None}
            continue
        current.append(row)
        if row["user_id"] is not None:
            participants.add(row["user_id"])
    segments.append(current)
    return segments


def dedup_segments(segments: list[list[dict]]) -> list[list[dict]]:
    """Снять дубли сегментов по стабильному ключу (overlap границ batch)."""
    seen: set[str] = set()
    out: list[list[dict]] = []
    for segment in segments or ():
        key = segment_key([str(m.get("message_key")) for m in segment])
        if key in seen:
            continue
        seen.add(key)
        out.append(segment)
    return out


def segment_times(segment: list[dict]) -> tuple[int | None, int | None]:
    """`(event_start, event_end)` сегмента — по времени исходных сообщений
    (A11: не по дате обнаружения)."""
    timestamps = [int(m.get("timestamp") or 0) for m in segment or ()]
    timestamps = [ts for ts in timestamps if ts > 0]
    if not timestamps:
        return None, None
    return min(timestamps), max(timestamps)


def split_by_participant_clusters(segment: list[dict]) -> list[list[dict]]:
    """Детерминированный сплит много-топикового сегмента по кластерам
    участников (сигнал «участники», D4): сообщения группируются по автору;
    авторы объединяются в кластер только reply-связью внутри сегмента;
    кластеры без reply-связей — независимые разговоры. Порядок сообщений/
    время не меняются; один кластер → сегмент возвращается как есть
    (без выдуманных сплитов)."""
    rows = [dict(m) for m in segment or ()]
    if len(rows) <= 1:
        return [rows] if rows else []
    index = {str(_field(m, "message_key") or message_key(m)): m
             for m in rows}
    # Кластеры авторов: reply между авторами объединяет их кластеры.
    author_ids = [_normalize_id(m.get("user_id")) for m in rows]
    author_list = [a for a in dict.fromkeys(
        a for a in author_ids if a is not None)]
    author_index = {a: i for i, a in enumerate(author_list)}
    parent = list(range(len(author_list)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def union(i, j):
        ri, rj = find(i), find(j)
        if ri != rj:
            parent[max(ri, rj)] = min(ri, rj)

    for m in rows:
        author = _normalize_id(m.get("user_id"))
        if author is None:
            continue
        rtk = _field(m, "reply_to_key") or reply_key(m)
        if not rtk:
            continue
        target = index.get(str(rtk))
        if target is None:
            continue
        target_author = _normalize_id(target.get("user_id"))
        if target_author is not None and target_author != author:
            union(author_index[author], author_index[target_author])
    groups: dict[int, list[dict]] = {}
    for m in rows:
        author = _normalize_id(m.get("user_id"))
        root = find(author_index[author]) if author is not None else -1
        groups.setdefault(root, []).append(m)
    if len(groups) <= 1:
        return [rows]
    out = [sorted(group, key=lambda m: (int(_field(m, "timestamp") or 0),
                                        str(_field(m, "message_key")
                                             or message_key(m))))
           for group in groups.values()]
    out.sort(key=lambda g: (int(_field(g[0], "timestamp") or 0),
                            str(_field(g[0], "message_key")
                                or message_key(g[0]))))
    return out


# ── сборка истории: повторы/противоречия (D7, §9.2 п.5–6) ──────────────────

def normalize_claim_text(text: str) -> str:
    """Нормализация текста утверждения (дедуп повторов)."""
    return _WS_RE.sub(" ", str(text or "").casefold()).strip()


def claim_signature(text: str) -> frozenset[str]:
    """Подпись сущности утверждения (токены >=3 симв.) — детерминированная
    canonical event-идентичность (повтор ≠ независимое событие)."""
    from services.mca_episode_prompts import entity_tokens
    return frozenset(entity_tokens(text))


def merge_claims(claims: list[dict]) -> tuple[list[dict], int]:
    """Объединить утверждения без потери различий: точный повтор (та же
    нормализованная форма) — увеличивает ``repeat_count`` и НЕ добавляет
    независимость; разные формулировки сохраняются."""
    merged: list[dict] = []
    repeats = 0
    by_norm: dict[str, dict] = {}
    for claim in claims or ():
        text = str(claim.get("text") or "")
        norm = normalize_claim_text(text)
        if not norm:
            continue
        existing = by_norm.get(norm)
        if existing is not None:
            existing["repeat_count"] = int(existing.get("repeat_count") or 1) + 1
            for ref in claim.get("refs") or ():
                if ref not in existing["refs"]:
                    existing["refs"].append(ref)
            repeats += 1
            continue
        entry = {"text": text, "refs": list(claim.get("refs") or ()),
                 "repeat_count": 1}
        by_norm[norm] = entry
        merged.append(entry)
    return merged[:STORY_CLAIMS_MAX], repeats


def detect_contradictions(claims: list[dict]) -> list[tuple[str, str]]:
    """Детерминированный детект противоречий (не разрешает молча): пара
    утверждений с общей подписью сущности (≥2 общих токена), но разной
    полярностью (наличие отрицания). Оба утверждения СОХРАНЯЮТСЯ."""
    polarities: list[tuple[str, int, frozenset[str]]] = []
    for claim in claims or ():
        text = str(claim.get("text") or "")
        folded = text.casefold()
        polarity = -1 if any(marker in folded
                             for marker in _NEGATION_MARKERS) else 1
        polarities.append((text, polarity, claim_signature(text)))
    conflicts: list[tuple[str, str]] = []
    for i in range(len(polarities)):
        for j in range(i + 1, len(polarities)):
            text_a, pol_a, sig_a = polarities[i]
            text_b, pol_b, sig_b = polarities[j]
            if pol_a == pol_b or len(sig_a & sig_b) < 2:
                continue
            pair = (text_a, text_b) if text_a <= text_b else (text_b, text_a)
            if pair not in conflicts:
                conflicts.append(pair)
    return conflicts


# ── модели записей ───────────────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class EpisodeRecord:
    """Эпизод разговора (карточка §9.1, ADR-1027-12 §5)."""
    episode_id: str
    chat_id: int
    title: str
    summary: str
    participants: tuple[str, ...]
    event_start_ts: int | None
    event_end_ts: int | None
    discovered_at: int
    updated_at: int
    claims: tuple[dict, ...]
    outcome: str
    outcome_known: bool
    open_questions: tuple[str, ...]
    message_keys: tuple[str, ...]
    segment_key: str
    extraction_version: str
    mapping_status: str = "unmapped"
    recheck_pending: int = 0


def effective_story(row: dict) -> dict:
    """Эффективная карточка истории: ручные override-поля применяются
    поверх автоматических (override пайплайном никогда не затирается)."""
    story = dict(row or {})
    for field in ("title", "summary", "outcome", "state", "open_questions"):
        override = story.get(f"override_{field}")
        if override:
            story[field] = override
    return story


def _field(row, key, default=None):
    try:
        if isinstance(row, dict):
            return row.get(key, default)
        return row[key]
    except (KeyError, IndexError, TypeError):
        return default


def _normalize_id(value):
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _json_loads(raw, default):
    try:
        data = json.loads(raw) if raw else default
        return data if data is not None else default
    except (ValueError, TypeError):
        return default


def _json_dumps(data) -> str:
    return json.dumps(data or [], ensure_ascii=False)


def _now(now: int | None) -> int:
    return int(time.time()) if now is None else int(now)


def _uuid() -> str:
    return uuid.uuid4().hex


# ── Repository: весь SQL mca-05 (GEN-R21; UI/пайплайн не ходят в БД напрямую)

class EpisodeRepository:
    """Repository-слой SQL модели Episode/Story (v21).

    Чтения — fail-open (пустой результат + WARNING); записи — через
    `db.write_transaction` (single-writer `mca-01`, короткие транзакции).
    """

    def __init__(self, db) -> None:
        self._db = db

    # ── чтения (fail-open) ────────────────────────────────────────────────

    async def _fetch_all(self, sql: str, params=()) -> list[dict]:
        try:
            cursor = await self._db.db.execute(sql, params)
            return [dict(r) for r in await cursor.fetchall()]
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("[mca05] repository read failed", exc_info=True)
            return []

    async def _fetch_one(self, sql: str, params=()) -> dict | None:
        rows = await self._fetch_all(sql, params)
        return rows[0] if rows else None

    async def get_episode(self, episode_id: str) -> dict | None:
        return await self._fetch_one(
            "SELECT * FROM mca_episodes WHERE episode_id = ?",
            (str(episode_id),))

    async def list_episodes(self, chat_id: int, limit: int = 200) -> list[dict]:
        return await self._fetch_all(
            "SELECT * FROM mca_episodes WHERE chat_id = ? "
            "ORDER BY updated_at DESC, episode_id LIMIT ?",
            (int(chat_id), max(1, int(limit))))

    async def find_episode_by_segment(self, chat_id: int,
                                      seg_key: str) -> dict | None:
        return await self._fetch_one(
            "SELECT * FROM mca_episodes WHERE chat_id = ? AND segment_key = ?",
            (int(chat_id), str(seg_key)))

    async def get_story(self, story_id: str) -> dict | None:
        return await self._fetch_one(
            "SELECT * FROM mca_stories WHERE story_id = ?", (str(story_id),))

    async def list_stories(self, chat_id: int, limit: int = 200) -> list[dict]:
        return await self._fetch_all(
            "SELECT * FROM mca_stories WHERE chat_id = ? "
            "ORDER BY updated_at DESC, story_id LIMIT ?",
            (int(chat_id), max(1, int(limit))))

    async def list_story_versions(self, story_id: str) -> list[dict]:
        return await self._fetch_all(
            "SELECT * FROM mca_story_versions WHERE story_id = ? "
            "ORDER BY version_no ASC", (str(story_id),))

    async def get_story_version(self, version_id: str) -> dict | None:
        return await self._fetch_one(
            "SELECT * FROM mca_story_versions WHERE version_id = ?",
            (str(version_id),))

    async def story_episode_ids(self, story_id: str) -> list[str]:
        rows = await self._fetch_all(
            "SELECT episode_id FROM mca_story_episode_links "
            "WHERE story_id = ? ORDER BY order_no, episode_id",
            (str(story_id),))
        return [r["episode_id"] for r in rows]

    async def story_ids_for_episode(self, episode_id: str) -> list[str]:
        rows = await self._fetch_all(
            "SELECT story_id FROM mca_story_episode_links WHERE episode_id = ?",
            (str(episode_id),))
        return [r["story_id"] for r in rows]

    async def list_continuations(self, episode_ids: list[str]) -> list[dict]:
        if not episode_ids:
            return []
        placeholders = ",".join("?" * min(len(episode_ids), 400))
        bounded = list(episode_ids)[:400]
        return await self._fetch_all(
            "SELECT * FROM mca_story_continuations WHERE "
            f"from_episode_id IN ({placeholders}) "
            f"OR to_episode_id IN ({placeholders})",
            bounded + bounded)

    async def get_legacy_link(self, lore_story_id: int) -> dict | None:
        return await self._fetch_one(
            "SELECT * FROM mca_story_legacy_links WHERE lore_story_id = ?",
            (int(lore_story_id),))

    async def list_legacy_links(self, limit: int = 500) -> list[dict]:
        return await self._fetch_all(
            "SELECT * FROM mca_story_legacy_links LIMIT ?",
            (max(1, int(limit)),))

    async def redirect_target(self, kind: str, old_id: str) -> str | None:
        row = await self._fetch_one(
            "SELECT new_kind, new_id FROM mca_story_redirects "
            "WHERE old_kind = ? AND old_id = ?", (str(kind), str(old_id)))
        if row is None:
            return None
        # Резолв цепочки redirect — bounded (защита от цикла).
        current_kind, current_id = str(row["new_kind"]), str(row["new_id"])
        for _ in range(8):
            nxt = await self._fetch_one(
                "SELECT new_kind, new_id FROM mca_story_redirects "
                "WHERE old_kind = ? AND old_id = ?",
                (current_kind, current_id))
            if nxt is None:
                break
            current_kind, current_id = str(nxt["new_kind"]), str(nxt["new_id"])
        return current_id if current_kind == str(kind) else current_id

    async def list_recheck_episodes(self, chat_id: int,
                                    limit: int = 20) -> list[dict]:
        return await self._fetch_all(
            "SELECT * FROM mca_episodes WHERE chat_id = ? AND "
            "recheck_pending = 1 ORDER BY updated_at ASC, episode_id LIMIT ?",
            (int(chat_id), max(1, int(limit))))

    # ── записи (write_transaction, короткие) ──────────────────────────────

    async def insert_episode(self, *, chat_id: int, title: str, summary: str,
                             participants: list[str], claims: list[dict],
                             event_start: int | None, event_end: int | None,
                             outcome: str, outcome_known: bool,
                             open_questions: list[str],
                             message_keys: list[str], seg_key: str,
                             extraction_version: str,
                             now: int) -> str | None:
        """Создать эпизод (idempotent по `(chat_id, segment_key)` — overlap
        без дублей). Возвращает `episode_id` или None (дубль/ошибка)."""
        episode_id = _uuid()
        sql = ("INSERT OR IGNORE INTO mca_episodes (episode_id, chat_id, "
               "title, summary, participants_json, event_start_ts, "
               "event_end_ts, discovered_at, updated_at, claims_json, "
               "outcome, open_questions, message_keys_json, segment_key, "
               "extraction_version, mapping_status) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?, 'unmapped')")

        async def _body(_conn):
            cursor = await self._db.db.execute(sql, (
                episode_id, int(chat_id), str(title or ""),
                str(summary or ""), _json_dumps(list(participants or ())),
                event_start, event_end, int(now), int(now),
                _json_dumps(list(claims or ())), str(outcome or ""),
                _json_dumps(list(open_questions or ())),
                _json_dumps(list(message_keys or ())), str(seg_key),
                str(extraction_version or EXTRACTOR_VERSION)))
            return cursor.rowcount

        try:
            created = await self._db.write_transaction(
                _body, op_name="mca05_episode_insert")
            return episode_id if created else None
        except Exception:
            logger.warning("[mca05] episode insert failed", exc_info=True)
            return None

    async def set_episode_recheck(self, episode_id: str, *,
                                  pending: bool = True) -> bool:
        sql = ("UPDATE mca_episodes SET recheck_pending = ?, updated_at = ? "
               "WHERE episode_id = ?")

        async def _body(_conn):
            cursor = await self._db.db.execute(sql, (
                1 if pending else 0, int(time.time()), str(episode_id)))
            return cursor.rowcount

        try:
            return bool(await self._db.write_transaction(
                _body, op_name="mca05_episode_recheck"))
        except Exception:
            logger.warning("[mca05] episode recheck flag failed",
                           exc_info=True)
            return False

    async def upsert_continuation(self, from_episode_id: str,
                                  to_episode_id: str, *,
                                  status: str, confirmation: dict | None,
                                  now: int) -> bool:
        if status not in EPISODE_CONTINUATION_STATUSES:
            status = "candidate"
        sql = ("INSERT INTO mca_story_continuations (from_episode_id, "
               "to_episode_id, confirmation_json, status, created_at) "
               "VALUES (?,?,?,?,?) ON CONFLICT(from_episode_id, "
               "to_episode_id) DO UPDATE SET status = excluded.status, "
               "confirmation_json = excluded.confirmation_json")

        async def _body(_conn):
            cursor = await self._db.db.execute(sql, (
                str(from_episode_id), str(to_episode_id),
                _json_dumps(confirmation) if confirmation else None,
                str(status), int(now)))
            return cursor.rowcount

        try:
            await self._db.write_transaction(
                _body, op_name="mca05_continuation_upsert")
            return True
        except Exception:
            logger.warning("[mca05] continuation upsert failed",
                           exc_info=True)
            return False

    async def _insert_story_version_locked(self, story_id: str, version_no: int,
                                           payload: dict, created_by: str,
                                           extractor_version: str,
                                           now: int) -> str:
        version_id = _uuid()
        await self._db.db.execute(
            "INSERT INTO mca_story_versions (version_id, story_id, "
            "version_no, payload_json, created_at, created_by, "
            "extractor_version) VALUES (?,?,?,?,?,?,?)",
            (version_id, str(story_id), int(version_no),
             _json_dumps(payload), int(now), str(created_by),
             str(extractor_version or "")))
        return version_id

    async def upsert_story(self, *, chat_id: int, title: str, summary: str,
                           participants: list[str], claims: list[dict],
                           event_start: int | None, event_end: int | None,
                           outcome: str, state: str, verification: str,
                           open_questions: list[str],
                           episode_ids: list[str], extractor_version: str,
                           now: int, created_by: str = "pipeline",
                           discovered_at: int | None = None,
                           ) -> tuple[str, str, bool]:
        """Создать/пересобрать историю: новая версия (полный снимок) на
        каждое изменение; override-колонки НЕ затираются и переносятся в
        снимок (A13). Возврат ``(story_id, active_version_id, created)``.

        История без эпизодов запрещена (≥1 эпизод, §9.1)."""
        if state not in EPISODE_STORY_STATES:
            state = "open"
        if str(verification) not in ("verified", "rejected", "tentative",
                                     "unknown"):
            verification = "unknown"
        episode_ids = [str(e) for e in (episode_ids or ())][: _STORY_EPS_CAP]
        if not episode_ids:
            raise ValueError("story requires >=1 episode")

        async def _body(_conn):
            row = None
            # Каноническая идентичность: история, уже содержащая ЛЮБОЙ
            # эпизод компонента (component-identity, не topic_key).
            for episode_id in episode_ids:
                cursor = await self._db.db.execute(
                    "SELECT s.* FROM mca_stories s JOIN "
                    "mca_story_episode_links l ON l.story_id = s.story_id "
                    "WHERE l.episode_id = ? LIMIT 1", (episode_id,))
                row = await cursor.fetchone()
                if row is not None:
                    break
            if row is not None:
                row = dict(row)
                story_id = row["story_id"]
                overrides = {name: row.get(f"override_{name}")
                             for name in ("title", "summary", "outcome",
                                          "state", "open_questions")}
                links = await self._db.db.execute(
                    "SELECT episode_id FROM mca_story_episode_links "
                    "WHERE story_id = ?", (story_id,))
                existing_eps = [r["episode_id"] for r in
                                await links.fetchall()]
                for episode_id in episode_ids:
                    await self._db.db.execute(
                        "INSERT OR IGNORE INTO mca_story_episode_links "
                        "(story_id, episode_id, order_no) VALUES (?,?,?)",
                        (story_id, episode_id, len(existing_eps)))
                final_eps = list(dict.fromkeys(
                    existing_eps + [e for e in episode_ids
                                    if e not in existing_eps]))
                version_no = int(row.get("expected_version") or 1) + 1
                payload = {
                    "title": title, "summary": summary,
                    "participants": list(participants or ()),
                    "claims": list(claims or ()),
                    "event_start_ts": event_start, "event_end_ts": event_end,
                    "outcome": outcome, "state": state,
                    "verification": verification,
                    "open_questions": list(open_questions or ()),
                    "episode_ids": final_eps,
                    "overrides": {k: v for k, v in overrides.items()
                                  if v is not None},
                }
                version_id = await self._insert_story_version_locked(
                    story_id, version_no, payload, created_by,
                    extractor_version, now)
                await self._db.db.execute(
                    "UPDATE mca_stories SET title = ?, summary = ?, "
                    "participants_json = ?, event_start_ts = ?, "
                    "event_end_ts = ?, updated_at = ?, claims_json = ?, "
                    "outcome = ?, state = ?, verification = ?, "
                    "open_questions = ?, active_version_id = ?, "
                    "expected_version = ?, extractor_version = ? "
                    "WHERE story_id = ?",
                    (title, summary, _json_dumps(list(participants or ())),
                     event_start, event_end, int(now),
                     _json_dumps(list(claims or ())), outcome, state,
                     verification, _json_dumps(list(open_questions or ())),
                     version_id, version_no, extractor_version, story_id))
                return (story_id, version_id, False)
            story_id = _uuid()
            payload = {
                "title": title, "summary": summary,
                "participants": list(participants or ()),
                "claims": list(claims or ()),
                "event_start_ts": event_start, "event_end_ts": event_end,
                "outcome": outcome, "state": state,
                "verification": verification,
                "open_questions": list(open_questions or ()),
                "episode_ids": episode_ids, "overrides": {},
            }
            version_id = await self._insert_story_version_locked(
                story_id, 1, payload, created_by, extractor_version, now)
            await self._db.db.execute(
                "INSERT INTO mca_stories (story_id, chat_id, title, summary, "
                "participants_json, event_start_ts, event_end_ts, "
                "discovered_at, updated_at, claims_json, outcome, "
                "open_questions, state, verification, "
                "excluded_from_retrieval, active_version_id, "
                "expected_version, extractor_version, task_status_ref) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,1,?,NULL)",
                (story_id, int(chat_id), title, summary,
                 _json_dumps(list(participants or ())), event_start,
                 event_end, int(discovered_at if discovered_at is not None
                                 else now), int(now),
                 _json_dumps(list(claims or ())), outcome,
                 _json_dumps(list(open_questions or ())), state, verification,
                 version_id, extractor_version))
            for order_no, episode_id in enumerate(episode_ids):
                await self._db.db.execute(
                    "INSERT OR IGNORE INTO mca_story_episode_links "
                    "(story_id, episode_id, order_no) VALUES (?,?,?)",
                    (story_id, episode_id, order_no))
            return (story_id, version_id, True)

        try:
            return await self._db.write_transaction(
                _body, op_name="mca05_story_upsert")
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.warning("[mca05] story upsert failed", exc_info=True)
            return ("", "", False)

    async def update_story_manual(self, story_id: str, expected_version: int,
                                  *, title=None, summary=None, outcome=None,
                                  state=None, open_questions=None,
                                  extractor_version: str = "",
                                  now: int | None = None) -> str:
        """Ручная правка (CAS `expected_version`): пишет override-поля +
        версию `created_by='manual'`. Stale update → StaleUpdateError
        (отклоняется, не затирает)."""
        if state is not None and state not in EPISODE_STORY_STATES:
            raise ValueError(f"story state invalid: {state!r}")
        ts = _now(now)

        async def _body(_conn):
            cursor = await self._db.db.execute(
                "SELECT * FROM mca_stories WHERE story_id = ?",
                (str(story_id),))
            row = await cursor.fetchone()
            if row is None:
                raise KeyError(f"story not found: {story_id}")
            row = dict(row)
            current = int(row.get("expected_version") or 1)
            if current != int(expected_version):
                raise StaleUpdateError(
                    f"stale update: expected {expected_version}, "
                    f"actual {current}")
            sets = ["updated_at = ?", "expected_version = ?"]
            params: list = [ts, current + 1]
            payload_overrides = {}
            for field, value in (("title", title), ("summary", summary),
                                 ("outcome", outcome), ("state", state),
                                 ("open_questions", open_questions)):
                if value is None:
                    continue
                stored = (_json_dumps(list(value)) if field ==
                          "open_questions" else str(value))
                # Ручная правка: базовая колонка (единый источник значения)
                # + override-маркер (переживает пересборку — A13).
                sets.append(f"{field} = ?")
                params.append(stored)
                sets.append(f"override_{field} = ?")
                params.append(stored)
                payload_overrides[field] = stored
            payload = {
                "title": title if title is not None else row.get("title"),
                "summary": (summary if summary is not None
                            else row.get("summary")),
                "participants": _json_loads(row.get("participants_json"), []),
                "claims": _json_loads(row.get("claims_json"), []),
                "event_start_ts": row.get("event_start_ts"),
                "event_end_ts": row.get("event_end_ts"),
                "outcome": (outcome if outcome is not None
                            else row.get("outcome")),
                "state": (state if state is not None else row.get("state")),
                "verification": row.get("verification"),
                "open_questions": (list(open_questions)
                                   if open_questions is not None else
                                   _json_loads(row.get("open_questions"),
                                               [])),
                "episode_ids": await self._episode_ids_locked(story_id),
                "overrides": payload_overrides,
                "manual": True,
            }
            version_no = current + 1
            version_id = await self._insert_story_version_locked(
                story_id, version_no, payload, "manual", extractor_version,
                ts)
            sets.extend(["active_version_id = ?"])
            params.append(version_id)
            params.append(str(story_id))
            await self._db.db.execute(
                f"UPDATE mca_stories SET {', '.join(sets)} "
                "WHERE story_id = ?", tuple(params))
            return version_id

        return await self._db.write_transaction(
            _body, op_name="mca05_story_manual")

    async def _episode_ids_locked(self, story_id: str) -> list[str]:
        cursor = await self._db.db.execute(
            "SELECT episode_id FROM mca_story_episode_links "
            "WHERE story_id = ? ORDER BY order_no, episode_id",
            (str(story_id),))
        return [r["episode_id"] for r in await cursor.fetchall()]

    async def set_story_task_ref(self, story_id: str, task_status_ref) -> bool:
        """Статус задания обработки — ОТДЕЛЬНОЕ поле (`task_status_ref`);
        НЕ трогает `state` (инвариант «состояние истории ≠ статус job»)."""
        sql = "UPDATE mca_stories SET task_status_ref = ?, updated_at = ? " \
              "WHERE story_id = ?"

        async def _body(_conn):
            cursor = await self._db.db.execute(sql, (
                str(task_status_ref) if task_status_ref is not None else None,
                int(time.time()), str(story_id)))
            return cursor.rowcount

        try:
            return bool(await self._db.write_transaction(
                _body, op_name="mca05_story_task_ref"))
        except Exception:
            logger.warning("[mca05] story task_ref update failed",
                           exc_info=True)
            return False

    async def set_story_excluded(self, story_id: str, excluded: bool) -> bool:
        sql = "UPDATE mca_stories SET excluded_from_retrieval = ?, " \
              "updated_at = ? WHERE story_id = ?"

        async def _body(_conn):
            cursor = await self._db.db.execute(sql, (
                1 if excluded else 0, int(time.time()), str(story_id)))
            return cursor.rowcount

        try:
            return bool(await self._db.write_transaction(
                _body, op_name="mca05_story_excluded"))
        except Exception:
            logger.warning("[mca05] story excluded update failed",
                           exc_info=True)
            return False

    async def insert_redirect(self, old_kind: str, old_id: str,
                              new_kind: str, new_id: str, *,
                              now: int | None = None) -> bool:
        sql = ("INSERT OR IGNORE INTO mca_story_redirects (old_kind, old_id, "
               "new_kind, new_id, created_at) VALUES (?,?,?,?,?)")

        async def _body(_conn):
            cursor = await self._db.db.execute(sql, (
                str(old_kind), str(old_id), str(new_kind), str(new_id),
                _now(now)))
            return cursor.rowcount

        try:
            return bool(await self._db.write_transaction(
                _body, op_name="mca05_redirect_insert"))
        except Exception:
            logger.warning("[mca05] redirect insert failed", exc_info=True)
            return False

    async def upsert_legacy_link(self, lore_story_id: int, *,
                                 story_id: str | None,
                                 mapping_status: str,
                                 now: int | None = None) -> bool:
        if mapping_status not in EPISODE_MAPPING_STATUSES:
            mapping_status = "unmapped"
        sql = ("INSERT INTO mca_story_legacy_links (lore_story_id, story_id, "
               "mapping_status, updated_at) VALUES (?,?,?,?) "
               "ON CONFLICT(lore_story_id) DO UPDATE SET story_id = "
               "excluded.story_id, mapping_status = excluded.mapping_status, "
               "updated_at = excluded.updated_at")

        async def _body(_conn):
            cursor = await self._db.db.execute(sql, (
                int(lore_story_id), str(story_id) if story_id else None,
                str(mapping_status), _now(now)))
            return cursor.rowcount

        try:
            return bool(await self._db.write_transaction(
                _body, op_name="mca05_legacy_link"))
        except Exception:
            logger.warning("[mca05] legacy link upsert failed",
                           exc_info=True)
            return False

    async def merge_stories(self, source_ids: list[str], target_id: str, *,
                            extractor_version: str = "",
                            now: int | None = None) -> bool:
        """Merge: ссылки эпизодов переезжают на target (новая версия
        создаётся вызывающим `upsert_story`), источники получают redirect
        и скрываются из выдачи фасада; история сохраняется."""
        ts = _now(now)

        async def _body(_conn):
            for source_id in source_ids:
                if str(source_id) == str(target_id):
                    continue
                await self._db.db.execute(
                    "INSERT OR IGNORE INTO mca_story_episode_links "
                    "(story_id, episode_id, order_no) "
                    "SELECT ?, episode_id, order_no FROM "
                    "mca_story_episode_links WHERE story_id = ?",
                    (str(target_id), str(source_id)))
                await self._db.db.execute(
                    "DELETE FROM mca_story_episode_links WHERE story_id = ?",
                    (str(source_id),))
                await self._db.db.execute(
                    "INSERT OR IGNORE INTO mca_story_redirects (old_kind, "
                    "old_id, new_kind, new_id, created_at) VALUES "
                    "('story', ?, 'story', ?, ?)",
                    (str(source_id), str(target_id), ts))
            return True

        try:
            return bool(await self._db.write_transaction(
                _body, op_name="mca05_story_merge"))
        except Exception:
            logger.warning("[mca05] story merge failed", exc_info=True)
            return False

    async def split_story(self, source_id: str, episode_ids: list[str], *,
                          extractor_version: str = "",
                          now: int | None = None) -> tuple[str, bool]:
        """Split (§9.2 `:334` «поддерживает merge/split», spec (h)/D9):
        отделить подмножество эпизодов в ОТДЕЛЬНУЮ историю; источник
        пересчитывается из оставшихся эпизодов (новая версия при
        изменении состава; override-колонки не трогаются).

        Семантика:
          * частичный сплит (в источнике остаётся ≥1 эпизод): обе истории
            живы, redirect НЕ создаётся (внешние ссылки на источник не
            ломаются — он существует);
          * «одиночный эпизод»: сплит истории из одного эпизода
            невозможен (отделять нечего — новая история совпала бы с
            источником) → no-op; если отделяются ВСЕ эпизоды — источник
            не может существовать (история ≥1 эпизода, §9.1): он
            удаляется, внешние ссылки спасает redirect на новую историю
            (spec (h): split пишет в `mca_story_redirects`).

        Возврат ``(new_story_id, ok)``. События с `reason_code=
        'story_split'` — только после фиксации (post-commit)."""
        ts = _now(now)
        requested = [str(e) for e in dict.fromkeys(episode_ids or ())]

        async def _body(_conn):
            cursor = await self._db.db.execute(
                "SELECT * FROM mca_stories WHERE story_id = ?",
                (str(source_id),))
            row = await cursor.fetchone()
            if row is None:
                return ("", False, None)
            source = dict(row)
            links = await self._db.db.execute(
                "SELECT episode_id FROM mca_story_episode_links "
                "WHERE story_id = ? ORDER BY order_no, episode_id",
                (str(source_id),))
            source_eps = [r["episode_id"] for r in await links.fetchall()]
            if len(source_eps) < 2:
                # Одиночный эпизод: отделять нечего.
                return ("", False, None)
            move_set = set(requested)
            if not move_set or not move_set <= set(source_eps):
                return ("", False, None)
            rows_by_id: dict[str, dict] = {}
            for eid in source_eps:
                cur = await self._db.db.execute(
                    "SELECT * FROM mca_episodes WHERE episode_id = ?",
                    (eid,))
                erow = await cur.fetchone()
                if erow is not None:
                    rows_by_id[eid] = dict(erow)

            def _card(ep_ids: list[str]) -> dict:
                # Детерминированный пересчёт карточки — те же правила,
                # что в `assemble_stories` (повторная сборка после сплита
                # не плодит лишнюю версию).
                member_rows = [rows_by_id[e] for e in ep_ids
                               if e in rows_by_id]
                starts = [int(r["event_start_ts"]) for r in member_rows
                          if r.get("event_start_ts")]
                ends = [int(r["event_end_ts"]) for r in member_rows
                        if r.get("event_end_ts")]
                participants: list[str] = []
                open_questions: list[str] = []
                for r in member_rows:
                    for pid in _json_loads(r.get("participants_json"), []):
                        if pid not in participants:
                            participants.append(pid)
                    for q in _json_loads(r.get("open_questions"), []):
                        if q not in open_questions:
                            open_questions.append(q)
                raw_claims: list[dict] = []
                for r in member_rows:
                    for claim in _json_loads(r.get("claims_json"), []):
                        raw_claims.append({
                            "text": str(claim.get("text") or ""),
                            "refs": list(claim.get("refs") or ())})
                claims, _repeats = merge_claims(raw_claims)
                known = [r for r in member_rows
                         if r.get("outcome") and r.get("outcome") !=
                         EPISODE_UNKNOWN_OUTCOME]
                if known:
                    outcome, state = known[0]["outcome"], "open"
                else:
                    # §9.1: неизвестный исход — «исход неизвестен».
                    outcome = EPISODE_UNKNOWN_OUTCOME
                    state = "uncertain"
                title = (member_rows[0].get("title") if member_rows
                         else "") or (f"История {min(starts)}" if starts
                                      else f"История {ts}")
                summary = " ".join(
                    str(r.get("summary") or "") for r in member_rows
                    if r.get("summary"))[:2000]
                return {"title": title, "summary": summary,
                        "participants": participants, "claims": claims,
                        "open_questions": open_questions,
                        "event_start": (min(starts) if starts else None),
                        "event_end": (max(ends) if ends else None),
                        "outcome": outcome, "state": state,
                        "verification": "unknown"}

            moved = [e for e in source_eps if e in move_set]
            remaining = [e for e in source_eps if e not in move_set]
            new_card = _card(moved)
            new_story_id = _uuid()
            new_version_id = await self._insert_story_version_locked(
                new_story_id, 1,
                {"title": new_card["title"], "summary": new_card["summary"],
                 "participants": new_card["participants"],
                 "claims": new_card["claims"],
                 "event_start_ts": new_card["event_start"],
                 "event_end_ts": new_card["event_end"],
                 "outcome": new_card["outcome"], "state": new_card["state"],
                 "verification": new_card["verification"],
                 "open_questions": new_card["open_questions"],
                 "episode_ids": moved, "overrides": {}},
                "manual", extractor_version, ts)
            await self._db.db.execute(
                "INSERT INTO mca_stories (story_id, chat_id, title, summary, "
                "participants_json, event_start_ts, event_end_ts, "
                "discovered_at, updated_at, claims_json, outcome, "
                "open_questions, state, verification, "
                "excluded_from_retrieval, active_version_id, "
                "expected_version, extractor_version, task_status_ref) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,0,?,1,?,NULL)",
                (new_story_id, int(source["chat_id"]), new_card["title"],
                 new_card["summary"], _json_dumps(new_card["participants"]),
                 new_card["event_start"], new_card["event_end"], ts, ts,
                 _json_dumps(new_card["claims"]), new_card["outcome"],
                 _json_dumps(new_card["open_questions"]), new_card["state"],
                 new_card["verification"], new_version_id,
                 str(extractor_version or "")))
            for order_no, episode_id in enumerate(moved):
                await self._db.db.execute(
                    "INSERT OR IGNORE INTO mca_story_episode_links "
                    "(story_id, episode_id, order_no) VALUES (?,?,?)",
                    (new_story_id, episode_id, order_no))
            if remaining:
                # Источник жив: пересчёт из оставшихся эпизодов (новая
                # версия; excluded/discovered_at не трогаются).
                await self._db.db.execute(
                    "DELETE FROM mca_story_episode_links WHERE story_id = ? "
                    "AND episode_id IN (%s)" % ",".join("?" * len(moved)),
                    (str(source_id), *moved))
                card = _card(remaining)
                version_no = int(source.get("expected_version") or 1) + 1
                overrides = {name: source.get(f"override_{name}")
                             for name in ("title", "summary", "outcome",
                                          "state", "open_questions")}
                version_id = await self._insert_story_version_locked(
                    str(source_id), version_no,
                    {"title": card["title"], "summary": card["summary"],
                     "participants": card["participants"],
                     "claims": card["claims"],
                     "event_start_ts": card["event_start"],
                     "event_end_ts": card["event_end"],
                     "outcome": card["outcome"], "state": card["state"],
                     "verification": card["verification"],
                     "open_questions": card["open_questions"],
                     "episode_ids": remaining,
                     "overrides": {k: v for k, v in overrides.items()
                                   if v is not None}},
                    "manual", extractor_version, ts)
                await self._db.db.execute(
                    "UPDATE mca_stories SET title = ?, summary = ?, "
                    "participants_json = ?, event_start_ts = ?, "
                    "event_end_ts = ?, updated_at = ?, claims_json = ?, "
                    "outcome = ?, state = ?, verification = ?, "
                    "open_questions = ?, active_version_id = ?, "
                    "expected_version = ?, extractor_version = ? "
                    "WHERE story_id = ?",
                    (card["title"], card["summary"],
                     _json_dumps(card["participants"]),
                     card["event_start"], card["event_end"], ts,
                     _json_dumps(card["claims"]), card["outcome"],
                     card["state"], card["verification"],
                     _json_dumps(card["open_questions"]), version_id,
                     version_no, str(extractor_version or ""),
                     str(source_id)))
                return (new_story_id, True, {
                    "chat_id": int(source["chat_id"]), "ts": ts,
                    "moved": moved, "remaining": remaining,
                    "card": new_card, "remaining_card": card,
                    "source_alive": True})
            # Отделяются ВСЕ эпизоды: источник не может существовать
            # (история ≥1 эпизода, §9.1) — redirect спасает внешние
            # ссылки; mapped legacy-ссылки переезжают на новую историю.
            await self._db.db.execute(
                "DELETE FROM mca_story_episode_links WHERE story_id = ?",
                (str(source_id),))
            await self._db.db.execute(
                "DELETE FROM mca_stories WHERE story_id = ?",
                (str(source_id),))
            await self._db.db.execute(
                "INSERT OR IGNORE INTO mca_story_redirects (old_kind, "
                "old_id, new_kind, new_id, created_at) VALUES "
                "('story', ?, 'story', ?, ?)",
                (str(source_id), new_story_id, ts))
            await self._db.db.execute(
                "UPDATE mca_story_legacy_links SET story_id = ?, "
                "updated_at = ? WHERE story_id = ?",
                (new_story_id, ts, str(source_id)))
            return (new_story_id, True, {
                "chat_id": int(source["chat_id"]), "ts": ts,
                "moved": moved, "remaining": [], "card": new_card,
                "remaining_card": None, "source_alive": False})

        try:
            new_story_id, ok, info = await self._db.write_transaction(
                _body, op_name="mca05_story_split")
        except Exception:
            logger.warning("[mca05] story split failed", exc_info=True)
            return ("", False)
        if not ok or info is None:
            return (str(new_story_id or ""), bool(ok))
        card = info["card"]
        emit_story_event(
            "story_discovered", outcome="success", chat_id=info["chat_id"],
            story_id=new_story_id, episode_ids=info["moved"],
            event_start=card["event_start"], event_end=card["event_end"],
            discovered_at=info["ts"], participants=card["participants"],
            summary=str(card["summary"] or "")[:200],
            reason_code="story_split", stage="assemble")
        if info["source_alive"]:
            src_card = info["remaining_card"] or card
            emit_story_event(
                "story_rebuilt", outcome="success",
                chat_id=info["chat_id"], story_id=str(source_id),
                episode_ids=info["remaining"],
                event_start=src_card["event_start"],
                event_end=src_card["event_end"],
                discovered_at=info["ts"],
                participants=src_card["participants"],
                summary=str(src_card["summary"] or "")[:200],
                reason_code="story_split", stage="assemble")
        return (new_story_id, True)


# ── события (REUSE mca-13; post-commit — только после фиксации) ─────────────

STOREFRONT_EVENTS = frozenset({
    "story_discovered", "story_extended", "source_linked",
    "contradiction_found", "story_rebuilt",
})
PIPELINE_STAGES = ("segment", "extract", "confirm", "assemble", "link",
                   "index")


def emit_story_event(event_name: str, *, outcome: str, chat_id: int,
                     story_id: str = "", episode_ids=(), event_start=None,
                     event_end=None, discovered_at=None, participants=(),
                     summary: str = "", reason_code: str | None = None,
                     level: str = "INFO", stage: str = "assemble",
                     pipeline_run_id: str | None = None) -> dict | None:
    """Событие витрины (§16.1: имена фиксированы — контракт mca-12).

    Поля (в `entity_ids` JSON + кодовых полях, spec (j)): story/episode
    refs, обе даты, участники-ID, краткое R17-safe описание. Вызывается
    ТОЛЬКО после фиксации результата (rollback → события нет)."""
    try:
        from services.mca_events import emit_mca_event
        entity = {
            "story_id": str(story_id or ""),
            "episode_ids": [str(e) for e in (episode_ids or ())][:20],
            "event_start": (int(event_start)
                            if event_start is not None else None),
            "event_end": (int(event_end) if event_end is not None else None),
            "discovered_at": (int(discovered_at)
                              if discovered_at is not None else None),
            "participants": [str(p) for p in (participants or ())][:50],
            "summary": str(summary or "")[:200],
        }
        return emit_mca_event(
            str(event_name), outcome=outcome, level=level,
            component="episodes", stage=str(stage)[:60],
            chat_id=int(chat_id), entity_ids=entity,
            reason_code=reason_code,
            pipeline_run_id=pipeline_run_id)
    except Exception:      # fail-open: контракт не рвёт поток
        return None


def emit_pipeline_stage(stage: str, outcome: str, *, chat_id: int,
                        reason_code: str | None = None,
                        level: str = "INFO",
                        pipeline_run_id: str | None = None,
                        **fields):
    """Стадийное событие пайплайна (mca-17a/§27.3: start+terminal outcome;
    стадии segment/extract/confirm/assemble/link/index)."""
    try:
        from services.mca_events import emit_mca_event
        return emit_mca_event(
            "episodes_build", outcome=outcome, level=level,
            component="episodes.build", stage=str(stage)[:60],
            chat_id=int(chat_id), reason_code=reason_code,
            pipeline_run_id=pipeline_run_id, **fields)
    except Exception:      # fail-open
        return None


# ── provenance (REUSE mca-04a; второй SourceRef-контракт запрещён) ──────────

async def record_episode_provenance(db, repo: "EpisodeRepository", *,
                                    chat_id: int, episode_id: str,
                                    message_keys: list[str],
                                    extractor_version: str) -> str:
    """SourceRef/EvidenceLink эпизода (§8.1: ≥1 валидная ссылка или явный
    unknown). Возвращает ``ok``|``unknown``. Ссылки — через существующие
    `mca_source_refs`/`mca_evidence_links` — второй контракт не создаётся."""
    from services import provenance as prov
    try:
        object_ref = await prov.resolve_source_ref(
            db, prov.SourceRef(
                store="sqlite", entity_type="episode",
                entity_id=str(episode_id), chat_id=int(chat_id),
                resolution="resolved").validate())
        if object_ref is None:
            return "unknown"
        linked = 0
        for key in (message_keys or ())[:200]:
            tg = None
            entity_id = str(key)
            if ":tg:" in str(key):
                try:
                    tg = int(str(key).rsplit(":tg:", 1)[1])
                except (TypeError, ValueError):
                    tg = None
                if tg is not None and not await _message_exists(
                        db, int(chat_id), tg_message_id=tg):
                    continue      # §8.1: сообщение не существует → не ссылка
                if tg is not None:
                    entity_id = await _smart_entity_id(db, int(chat_id), tg)
            elif ":db:" in str(key):
                entity_id = str(key).rsplit(":db:", 1)[1]
                if not await _message_exists(db, int(chat_id),
                                             db_id=entity_id):
                    continue
            msg_ref = await prov.resolve_source_ref(
                db, prov.message_source_ref(
                    chat_id=int(chat_id), entity_id=str(entity_id),
                    tg_message_id=tg, resolution="resolved"))
            if msg_ref is None:
                continue
            await prov.add_evidence_link(db, prov.EvidenceLink(
                subject_ref_id=int(object_ref),
                source_ref_id=int(msg_ref), link_type="derived_from",
                method="direct_reference", verification="verified",
                independence="independent",
                extractor_version=str(extractor_version
                                      or EXTRACTOR_VERSION),
                basis="episode: raw message"))
            linked += 1
        if linked <= 0:
            # §8.1: нет валидной ссылки — явный unknown (не выдуманная
            # ссылка), запись с честным origin_status.
            await prov.set_provenance_status(
                db, object_ref_id=int(object_ref), origin_status="unknown")
            emit_pipeline_stage("link", "silent", chat_id=chat_id,
                                reason_code="provenance_unresolved",
                                level="WARN")
            return "unknown"
        await prov.set_provenance_status(
            db, object_ref_id=int(object_ref), origin_status="original")
        return "ok"
    except Exception:
        logger.warning("[mca05] episode provenance failed", exc_info=True)
        return "unknown"


async def _smart_entity_id(db, chat_id: int, tg_message_id: int) -> str:
    """Канонический `smart_messages.id` при наличии строки, иначе
    `tg:<id>` (прецедент provenance._message_entity_id)."""
    try:
        cursor = await db.db.execute(
            "SELECT id FROM smart_messages WHERE chat_id = ? AND "
            "tg_message_id = ? LIMIT 1", (int(chat_id), int(tg_message_id)))
        row = await cursor.fetchone()
        if row is not None:
            return str(int(row["id"]))
    except Exception:
        pass
    return f"tg:{int(tg_message_id)}"


async def _message_exists(db, chat_id: int, *, tg_message_id=None,
                          db_id=None) -> bool:
    """Валидатор ссылки (§8.1): сообщение существует в chat scope."""
    try:
        if tg_message_id is not None:
            cursor = await db.db.execute(
                "SELECT 1 FROM smart_messages WHERE chat_id = ? AND "
                "tg_message_id = ? LIMIT 1", (int(chat_id),
                                              int(tg_message_id)))
        elif db_id is not None:
            cursor = await db.db.execute(
                "SELECT 1 FROM smart_messages WHERE chat_id = ? AND "
                "id = ? LIMIT 1", (int(chat_id), int(db_id)))
        else:
            return False
        return await cursor.fetchone() is not None
    except Exception:
        return False


async def record_story_provenance(db, *, chat_id: int, story_id: str,
                                  episode_ids: list[str],
                                  extractor_version: str) -> str:
    """SourceRef истории: `derived_from` на объектные SourceRef эпизодов
    (derived memory; §8.1)."""
    from services import provenance as prov
    try:
        object_ref = await prov.resolve_source_ref(
            db, prov.SourceRef(
                store="sqlite", entity_type="story",
                entity_id=str(story_id), chat_id=int(chat_id),
                resolution="resolved").validate())
        if object_ref is None:
            return "unknown"
        linked = 0
        for episode_id in (episode_ids or ())[:_STORY_EPS_CAP]:
            ep_ref = await prov.resolve_source_ref(
                db, prov.SourceRef(
                    store="sqlite", entity_type="episode",
                    entity_id=str(episode_id), chat_id=int(chat_id),
                    resolution="resolved"))
            if ep_ref is None:
                continue
            await prov.add_evidence_link(db, prov.EvidenceLink(
                subject_ref_id=int(object_ref),
                source_ref_id=int(ep_ref), link_type="derived_from",
                method="direct_reference", verification="tentative",
                independence="independent",
                extractor_version=str(extractor_version
                                      or EXTRACTOR_VERSION),
                basis="story: episode composition"))
            linked += 1
        if linked <= 0:
            await prov.set_provenance_status(
                db, object_ref_id=int(object_ref), origin_status="unknown")
            return "unknown"
        await prov.set_provenance_status(
            db, object_ref_id=int(object_ref), origin_status="original")
        return "ok"
    except Exception:
        logger.warning("[mca05] story provenance failed", exc_info=True)
        return "unknown"


async def validate_story_sources(db, story_id: str) -> str:
    """Валидатор ссылок (SC-11): ``ok`` — ≥1 валидный `derived_from`;
    ``unknown`` — явный unknown (ссылок нет, честный статус). Резолв
    SourceRef — по (store, entity_type, entity_id) независимо от chat_id
    (дедуп-ключ записи мог включать chat)."""
    from services import provenance as prov
    repo = EpisodeRepository(db)
    try:
        rows = await repo._fetch_all(
            "SELECT source_ref_id FROM mca_source_refs WHERE store = 'sqlite' "
            "AND entity_type = 'story' AND entity_id = ? "
            "ORDER BY source_ref_id LIMIT 1", (str(story_id),))
        if not rows:
            return "unknown"
        links = await prov.get_evidence_links(db, int(rows[0][
            "source_ref_id"]))
        derived = [link for link in links
                   if str(link.get("link_type")) == "derived_from"]
        return "ok" if derived else "unknown"
    except Exception:
        logger.warning("[mca05] story source validation failed",
                       exc_info=True)
        return "unknown"


# ── фасад интеграции (REUSE list-контракт; GEN-R19 — второй каталог
#    запрещён) ───────────────────────────────────────────────────────────────

async def list_stories_for_retrieval(db, chat_id: int,
                                     limit: int = 200) -> list[dict]:
    """Фасад для mca-07 episode-канала (D11): истории нового store +
    legacy `lore_stories` без mapped-связи. Форма строки — совместима с
    `list_lore_stories` (id/chat_id/topic/topic/story/last_ts/...) +
    `kind`. Уважает `excluded_from_retrieval`, chat scope и статусы
    (verification='rejected' не выдаётся); redirect-источники скрываются
    (резолв — `resolve_story_id`)."""
    repo = EpisodeRepository(db)
    out: list[dict] = []
    stories = await repo.list_stories(int(chat_id), limit=max(1, int(limit)))
    for row in stories:
        if int(row.get("excluded_from_retrieval") or 0):
            continue
        if str(row.get("verification") or "") == "rejected":
            continue
        story = effective_story(row)
        out.append({
            "id": story["story_id"], "chat_id": int(chat_id),
            "topic_key": "", "topic": str(story.get("title") or ""),
            "story": str(story.get("summary") or ""),
            "last_ts": int(story.get("event_end_ts")
                           or story.get("updated_at") or 0),
            "created_at": int(story.get("discovered_at") or 0),
            "updated_at": int(story.get("updated_at") or 0),
            "kind": "story",
        })
    redirected = {
        str(r.get("old_id")) for r in await repo._fetch_all(
            "SELECT old_id FROM mca_story_redirects WHERE old_kind = 'story'")
    }
    out = [row for row in out if str(row["id"]) not in redirected]
    try:
        cursor = await db.db.execute(
            "SELECT l.* FROM lore_stories l LEFT JOIN mca_story_legacy_links "
            "g ON g.lore_story_id = l.id WHERE l.chat_id = ? AND "
            "COALESCE(g.mapping_status, 'unmapped') != 'mapped' "
            "ORDER BY l.updated_at DESC LIMIT ?",
            (int(chat_id), max(1, int(limit))))
        for row in await cursor.fetchall():
            legacy = dict(row)
            legacy["kind"] = "legacy_story"
            out.append(legacy)
    except Exception:
        logger.warning("[mca05] legacy facade read failed", exc_info=True)
    out.sort(key=lambda r: int(r.get("updated_at") or 0), reverse=True)
    return out[:max(1, int(limit))]


async def resolve_story_id(db, story_id: str) -> str:
    """Redirect-резолв для внешних ссылок (mca-07 канал, будущие события
    mca-12/убеждений — ссылки не ломаются, D9)."""
    repo = EpisodeRepository(db)
    target = await repo.redirect_target("story", str(story_id))
    return str(target) if target else str(story_id)


async def build_local_context(db, chat_id: int, trigger_tg_message_id=None,
                              trigger_message_id=None, *,
                              limit: int = 6) -> tuple[str, ...]:
    """M-MCA07-2: наполнение `local_context` живого EvidenceBundle —
    истории, к которым принадлежит текущее сообщение (важный локальный
    контекст §11.2). Пусто → инвариант «not_available» (tuple())."""
    if not mca_gates.episodes_enabled():
        return ()
    try:
        repo = EpisodeRepository(db)
        key = None
        if trigger_tg_message_id is not None:
            key = f"{int(chat_id)}:tg:{int(trigger_tg_message_id)}"
        elif trigger_message_id is not None:
            key = f"{int(chat_id)}:db:{int(trigger_message_id)}"
        if not key:
            return ()
        matches: list[str] = []
        for episode in await repo.list_episodes(int(chat_id), limit=400):
            keys = set(_json_loads(episode.get("message_keys_json"), []))
            if key not in keys:
                continue
            for story_id in await repo.story_ids_for_episode(
                    episode["episode_id"]):
                story = await repo.get_story(story_id)
                if story is None:
                    continue
                card = effective_story(story)
                label = str(card.get("title") or "")[:80]
                matches.append(f"история:{story_id[:12]}:{label}"
                               if label else f"история:{story_id[:12]}")
        return tuple(dict.fromkeys(matches))[:max(1, int(limit))]
    except Exception:
        logger.warning("[mca05] local_context build failed", exc_info=True)
        return ()


async def note_compiler_touch(db, chat_id: int, lore_row: dict, *,
                              llm=None, now: int | None = None) -> str:
    """Фасад компилятора (D8): ленивый legacy-маппинг при касании БЕЗ
    автоматической ложной склейки. Связь — только по подтверждённой
    event-связи (LLM-подтверждение), никогда по равенству темы.
    Возвращает `mapping_status` записи."""
    if not mca_gates.episodes_compiler_facade_enabled():
        return "unmapped"
    repo = EpisodeRepository(db)
    lore_id = int(_field(lore_row, "id") or 0)
    if lore_id <= 0:
        return "unmapped"
    existing = await repo.get_legacy_link(lore_id)
    if existing is not None and str(
            existing.get("mapping_status")) == "mapped":
        return "mapped"
    if existing is None:
        await repo.upsert_legacy_link(
            lore_id, story_id=None, mapping_status="unmapped", now=now)
        emit_story_event(
            "story_discovered", outcome="skipped", chat_id=int(chat_id),
            story_id="", episode_ids=(),
            summary=f"legacy lore:{lore_id} unmapped",
            reason_code="story_legacy_unmapped", stage="link")
    if llm is None or not mca_gates.episodes_continuation_enabled():
        return "unmapped"
    # Кандидат маппинга — детерминированный (сущность/время), финальное
    # решение — LLM-подтверждение; равенство темы связью НЕ считается.
    from services.mca_episode_prompts import (
        build_confirm_system, build_confirm_user, entity_tokens,
        parse_confirm_answer, validate_confirm_payload,
    )
    story_rows = await repo.list_stories(int(chat_id), limit=50)
    topic = str(_field(lore_row, "topic") or "")
    story_text = str(_field(lore_row, "story") or "")
    last_ts = int(_field(lore_row, "last_ts") or 0)
    legacy_tokens = entity_tokens(topic) | entity_tokens(story_text)
    candidate = None
    for row in story_rows:
        card = effective_story(row)
        card_tokens = entity_tokens(str(card.get("title") or "")) | \
            entity_tokens(str(card.get("summary") or ""))
        if not (legacy_tokens & card_tokens):
            continue
        story_end = int(card.get("event_end_ts") or 0)
        if last_ts and story_end and abs(last_ts - story_end) > 90 * 86400:
            continue
        candidate = card
        break
    if candidate is None:
        return "unmapped"
    try:
        answer = await llm.generate(
            [{"role": "system", "content": build_confirm_system()},
             {"role": "user", "content": build_confirm_user(
                 event_a=f"пересказ компилятора: {story_text[:600]}",
                 event_b=(f"история {candidate.get('title')}: "
                          f"{str(candidate.get('summary') or '')[:600]}"))}],
            temperature=0.0, chat_id=int(chat_id))
        verdict = validate_confirm_payload(parse_confirm_answer(answer))
    except Exception:
        logger.warning("[mca05] legacy mapping confirm failed",
                       exc_info=True)
        return "unmapped"
    if not verdict.get("related"):
        return "unmapped"
    story_id = str(candidate.get("story_id") or "")
    await repo.upsert_legacy_link(
        lore_id, story_id=story_id, mapping_status="mapped", now=now)
    emit_story_event(
        "source_linked", outcome="success", chat_id=int(chat_id),
        story_id=story_id, episode_ids=(),
        summary=f"legacy lore:{lore_id} mapped",
        reason_code="provenance_linked", stage="link")
    return "mapped"


async def queue_source_recheck(db, chat_id: int,
                               message_keys: list[str] | set[str]) -> int:
    """Revision-реакция (D10): изменение источника (mca-03 revision)
    ставит зависимые эпизоды (и истории, где они состоят) на перепроверку —
    очередь, без немедленной рекурсивной ветки. Возврат — число помеченных
    эпизодов."""
    if not mca_gates.episodes_enabled():
        return 0
    repo = EpisodeRepository(db)
    keys = {str(k) for k in (message_keys or ())}
    if not keys:
        return 0
    marked = 0
    touched_stories: set[str] = set()
    for episode in await repo.list_episodes(int(chat_id), limit=500):
        episode_keys = set(_json_loads(episode.get("message_keys_json"), []))
        if not (episode_keys & keys):
            continue
        if int(episode.get("recheck_pending") or 0) == 1:
            continue
        if await repo.set_episode_recheck(episode["episode_id"]):
            marked += 1
        for story_id in await repo.story_ids_for_episode(
                episode["episode_id"]):
            touched_stories.add(str(story_id))
    if marked:
        emit_pipeline_stage(
            "index", "success", chat_id=int(chat_id),
            reason_code="story_source_recheck_queued",
            entity_ids={"episodes": marked,
                        "stories": len(touched_stories)})
    return marked


# ── EpisodeService: владелец пайплайна (D1/D4/D5/D7) ────────────────────────

class EpisodeService:
    """Пайплайн сборки эпизодов/историй (один владелец, D1).

    `llm` — существующий клиент (интерфейс `llm.generate(messages, *,
    temperature, chat_id)`, прецедент `LoreCompilerService`; GEN-R2).
    `None` → LLM-стадии честно пропускаются (fail-closed: связь не
    подтверждается, запись не выдумывается).
    """

    def __init__(self, db, llm=None, *, now=None) -> None:
        self._db = db
        self._llm = llm
        self._now = now
        self.repo = EpisodeRepository(db)

    # ── стадии ────────────────────────────────────────────────────────────

    async def process_batch(self, chat_id: int, messages: list[dict], *,
                            pipeline_run_id: str | None = None) -> dict:
        """Обработать порцию сообщений чата: сегментация → извлечение →
        продолжения → сборка → provenance/события/индекс. Возврат —
        счётчики (processed/extracted/linked/unresolved/errors/
        contradictions). Чтение → LLM → короткая запись разделены
        (никакой долгой транзакции, MCA14-R3)."""
        if not mca_gates.episodes_enabled():
            return {"enabled": False, "processed": 0, "extracted": 0,
                    "linked": 0, "unresolved": 0, "errors": 0,
                    "contradictions": 0}
        now = _now(self._now)
        counters = {"enabled": True, "processed": len(messages or ()),
                    "extracted": 0, "linked": 0, "unresolved": 0,
                    "errors": 0, "contradictions": 0}
        segments = dedup_segments(segment_messages(messages or ()))
        emit_pipeline_stage("segment", "success" if segments else "silent",
                            chat_id=chat_id, reason_code=(
                                None if segments else "story_segment_empty"),
                            pipeline_run_id=pipeline_run_id,
                            entity_ids={"segments": len(segments)})
        if not segments:
            return counters

        episode_ids: list[str] = []
        for segment in segments:
            try:
                episode_id = await self._process_segment(
                    chat_id, segment, now, counters,
                    pipeline_run_id=pipeline_run_id)
                if episode_id:
                    episode_ids.append(episode_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                counters["errors"] += 1
                emit_pipeline_stage(
                    "extract", "failed", chat_id=chat_id, level="ERROR",
                    reason_code="parse_error",
                    pipeline_run_id=pipeline_run_id)

        if episode_ids and mca_gates.episodes_continuation_enabled():
            try:
                counters["linked"] += await self._process_continuations(
                    chat_id, episode_ids, now,
                    pipeline_run_id=pipeline_run_id)
            except asyncio.CancelledError:
                raise
            except Exception:
                counters["errors"] += 1
                emit_pipeline_stage(
                    "confirm", "failed", chat_id=chat_id, level="ERROR",
                    reason_code="model_unavailable",
                    pipeline_run_id=pipeline_run_id)
        try:
            counters["contradictions"] += await self.assemble_stories(
                chat_id, now, pipeline_run_id=pipeline_run_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            counters["errors"] += 1
            emit_pipeline_stage(
                "assemble", "failed", chat_id=chat_id, level="ERROR",
                reason_code="parse_error", pipeline_run_id=pipeline_run_id)
        emit_pipeline_stage("index", "success", chat_id=chat_id,
                            pipeline_run_id=pipeline_run_id,
                            entity_ids={"episodes": len(episode_ids)})
        return counters

    async def _process_segment(self, chat_id: int, segment: list[dict],
                               now: int, counters: dict, *,
                               pipeline_run_id=None) -> str | None:
        """Извлечение одного сегмента (D5): LLM-контракт + офлайн-валидатор;
        дедуп по `(chat_id, segment_key)`/overlap-отношению; unknown не
        превращается в факт."""
        keys = [str(m.get("message_key")) for m in segment]
        seg_key = segment_key(keys)
        existing = await self.repo.find_episode_by_segment(chat_id, seg_key)
        if existing is not None:
            return None      # overlap без дублей
        if await self._find_overlap_duplicate(chat_id, keys):
            return None
        event_start, event_end = segment_times(segment)
        participant_ids = sorted({
            str(m["user_id"]) for m in segment
            if m.get("user_id") is not None})
        member_keys = set(keys)
        window_lines = [
            f"[{m.get('timestamp')}] {m.get('user_id')}: "
            f"{str(m.get('text') or '')[:300]}" for m in segment]
        payload = None
        if self._llm is not None:
            from services.mca_episode_prompts import (
                build_extract_system, build_extract_user,
                parse_extract_answer, validate_extract_payload,
            )
            try:
                raw = await self._llm.generate(
                    [{"role": "system", "content": build_extract_system()},
                     {"role": "user", "content": build_extract_user(
                         window_lines, participant_ids)}],
                    temperature=0.0, chat_id=int(chat_id))
                payload = validate_extract_payload(
                    parse_extract_answer(raw), member_keys=member_keys,
                    participant_ids=set(participant_ids))
                emit_pipeline_stage(
                    "extract",
                    "success" if payload.get("valid") else "failed",
                    chat_id=chat_id,
                    reason_code=None if payload.get("valid")
                    else "parse_error",
                    pipeline_run_id=pipeline_run_id)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                emit_pipeline_stage(
                    "extract", "failed", chat_id=chat_id, level="ERROR",
                    reason_code="model_unavailable",
                    pipeline_run_id=pipeline_run_id)
                logger.warning("[mca05] extract failed | chat=%s | err=%s",
                               chat_id, type(exc).__name__)
                # LLM-сбой — ошибка операции (backfill честно станет
                # paused); unresolved — производная честная недостача.
                counters["errors"] += 1
                counters["unresolved"] += 1
                return None
        if payload is not None and not payload.get("valid"):
            counters["unresolved"] += 1
            return None
        if payload is not None and payload.get("multi_topic"):
            # A12 (D4): LLM-топик-суждение «в подборке независимые
            # разговоры» → детерминированный сплит по кластерам участников
            # (reply-связность); каждый кластер извлекается отдельно.
            clusters = split_by_participant_clusters(segment)
            if len(clusters) > 1:
                created_any = None
                for cluster in clusters:
                    episode_id = await self._process_segment(
                        chat_id, cluster, now, counters,
                        pipeline_run_id=pipeline_run_id)
                    if episode_id:
                        created_any = episode_id
                return created_any
        if payload is not None:
            title = payload["title"] or f"Эпизод {event_start or ''}".strip()
            summary = payload["summary"]
            participants = payload["participants"]
            claims = payload["claims"]
            outcome = payload["outcome"]
            outcome_known = payload["outcome_known"]
            open_questions = payload["open_questions"]
            emit_pipeline_stage(
                "extract", "success", chat_id=chat_id,
                reason_code="episode_extracted",
                pipeline_run_id=pipeline_run_id)
        else:
            # Без LLM — детерминированная карточка (A11-путь): время из
            # исходных сообщений, содержимое не выдумывается.
            title = f"Эпизод {event_start or now}"
            summary = ""
            participants = participant_ids
            claims = []
            outcome = EPISODE_UNKNOWN_OUTCOME
            outcome_known = False
            open_questions = []
        episode_id = await self.repo.insert_episode(
            chat_id=chat_id, title=title, summary=summary,
            participants=participants, claims=claims,
            event_start=event_start, event_end=event_end, outcome=outcome,
            outcome_known=outcome_known, open_questions=open_questions,
            message_keys=keys, seg_key=seg_key,
            extraction_version=EXTRACTOR_VERSION, now=now)
        if episode_id is None:
            return None
        counters["extracted"] += 1
        status = await record_episode_provenance(
            self._db, self.repo, chat_id=chat_id, episode_id=episode_id,
            message_keys=keys, extractor_version=EXTRACTOR_VERSION)
        if status != "ok":
            counters["unresolved"] += 1
        return episode_id

    async def _find_overlap_duplicate(self, chat_id: int,
                                      keys: list[str]) -> bool:
        """Overlap-дедуп: сегмент, чей набор ключей ≥50% пересекается с уже
        существующим эпизодом чата — дубль (тот же эпизод, не новый)."""
        key_set = set(keys)
        if not key_set:
            return False
        for episode in await self.repo.list_episodes(chat_id, limit=500):
            episode_keys = set(_json_loads(
                episode.get("message_keys_json"), []))
            if not episode_keys:
                continue
            overlap = len(episode_keys & key_set) / max(
                len(episode_keys), len(key_set))
            if overlap >= 0.5:
                return True
        return False

    async def reextract_episode(self, chat_id: int, episode: dict,
                                messages: list[dict]) -> bool:
        """Перепроверка эпизода по исходным сообщениям (D10): повторное
        извлечение обновляет содержимое НА МЕСТЕ (episode_id/segment_key/
        discovered_at не меняются — A11); история получает новую версию
        при следующей сборке (изменение детектируется)."""
        if not messages:
            return False
        keys = [message_key(m) for m in messages]
        participant_ids = sorted({
            str(m.get("user_id")) for m in messages
            if m.get("user_id") is not None})
        member_keys = {str(k) for k in keys}
        payload = None
        if self._llm is not None:
            from services.mca_episode_prompts import (
                build_extract_system, build_extract_user,
                parse_extract_answer, validate_extract_payload,
            )
            window_lines = [
                f"[{m.get('timestamp')}] {m.get('user_id')}: "
                f"{str(m.get('text') or '')[:300]}" for m in messages]
            try:
                raw = await self._llm.generate(
                    [{"role": "system", "content": build_extract_system()},
                     {"role": "user", "content": build_extract_user(
                         window_lines, participant_ids)}],
                    temperature=0.0, chat_id=int(chat_id))
                payload = validate_extract_payload(
                    parse_extract_answer(raw), member_keys=member_keys,
                    participant_ids=set(participant_ids))
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("[mca05] recheck extract failed", exc_info=True)
                return False
            if payload is not None and not payload.get("valid"):
                return False
        if payload is not None:
            title = payload["title"] or str(episode.get("title") or "")
            summary = payload["summary"]
            claims = payload["claims"]
            outcome = payload["outcome"]
            open_questions = payload["open_questions"]
        else:
            title = str(episode.get("title") or "")
            summary = str(episode.get("summary") or "")
            claims = list(_json_loads(episode.get("claims_json"), []))
            outcome = EPISODE_UNKNOWN_OUTCOME
            open_questions = list(_json_loads(
                episode.get("open_questions"), []))
        ts = _now(self._now)
        sql = ("UPDATE mca_episodes SET title = ?, summary = ?, "
               "claims_json = ?, outcome = ?, open_questions = ?, "
               "updated_at = ?, extraction_version = ? WHERE episode_id = ?")

        async def _body(_conn):
            await self._db.db.execute(sql, (
                title, summary, _json_dumps(claims), outcome,
                _json_dumps(open_questions), ts,
                str(episode.get("extraction_version")
                    or EXTRACTOR_VERSION) + "+recheck",
                str(episode["episode_id"])))
            return 1

        try:
            await self._db.write_transaction(_body,
                                             op_name="mca05_reextract")
        except Exception:
            logger.warning("[mca05] reextract update failed", exc_info=True)
            return False
        emit_pipeline_stage("extract", "success", chat_id=chat_id,
                            reason_code="episode_extracted")
        return True

    async def _process_continuations(self, chat_id: int,
                                     episode_ids: list[str], now: int, *,
                                     pipeline_run_id=None) -> int:
        """Кандидаты продолжений по событию (D7): детерминированный фильтр
        (участники + сущность + время) → LLM-подтверждение до склейки.
        Тема/сходство — кандидат, не доказательство."""
        from services.mca_episode_prompts import (
            build_confirm_system, build_confirm_user, entity_tokens,
            is_continuation_candidate, parse_confirm_answer,
            validate_confirm_payload,
        )
        confirmed = 0
        all_episodes = await self.repo.list_episodes(chat_id, limit=400)
        new_set = {str(e) for e in episode_ids}
        seen_pairs: set[frozenset[str]] = set()
        for episode_id in episode_ids:
            episode = next((e for e in all_episodes
                            if str(e["episode_id"]) == str(episode_id)),
                           None)
            if episode is None:
                continue
            ep_tokens = entity_tokens(
                f"{episode.get('title')} {episode.get('summary')}")
            ep_participants = set(_json_loads(
                episode.get("participants_json"), []))
            candidates = 0
            for other in all_episodes:
                other_id = str(other["episode_id"])
                pair = frozenset((str(episode_id), other_id))
                if other_id == str(episode_id) or pair in seen_pairs:
                    continue
                seen_pairs.add(pair)
                if not is_continuation_candidate(
                        participants_a=ep_participants,
                        participants_b=set(_json_loads(
                            other.get("participants_json"), [])),
                        tokens_a=ep_tokens,
                        tokens_b=entity_tokens(
                            f"{other.get('title')} "
                            f"{other.get('summary')}"),
                        time_a=episode.get("event_start_ts"),
                        time_b=other.get("event_start_ts"), now=now):
                    continue
                candidates += 1
                if candidates > CONTINUATION_MAX_CANDIDATES:
                    break
                if self._llm is None:
                    # Без LLM связь не подтверждается (fail-closed).
                    await self.repo.upsert_continuation(
                        episode_id, other_id, status="candidate",
                        confirmation=None, now=now)
                    continue
                try:
                    raw = await self._llm.generate(
                        [{"role": "system",
                          "content": build_confirm_system()},
                         {"role": "user", "content": build_confirm_user(
                             event_a=(f"{episode.get('title')}: "
                                      f"{episode.get('summary')[:600]}"),
                             event_b=(f"{other.get('title')}: "
                                      f"{other.get('summary')[:600]}"),
                             time_a=str(episode.get("event_start_ts") or ""),
                             time_b=str(other.get("event_start_ts") or ""),
                             participants_a=",".join(ep_participants),
                             participants_b=",".join(_json_loads(
                                 other.get("participants_json"), [])))}],
                        temperature=0.0, chat_id=int(chat_id))
                    verdict = validate_confirm_payload(
                        parse_confirm_answer(raw))
                except asyncio.CancelledError:
                    raise
                except Exception:
                    emit_pipeline_stage(
                        "confirm", "failed", chat_id=chat_id, level="ERROR",
                        reason_code="model_unavailable",
                        pipeline_run_id=pipeline_run_id)
                    continue
                status = ("confirmed" if verdict.get("related")
                          else "rejected")
                await self.repo.upsert_continuation(
                    episode_id, other_id, status=status,
                    confirmation={"verdict": verdict,
                                  "canon": "continuation_confirm-1"},
                    now=now)
                emit_pipeline_stage(
                    "confirm", "success", chat_id=chat_id,
                    reason_code=("story_continuation_confirmed" if status
                                 == "confirmed"
                                 else "story_continuation_rejected"),
                    pipeline_run_id=pipeline_run_id,
                    entity_ids={"from": str(episode_id), "to": other_id})
                if status == "confirmed":
                    confirmed += 1
        return confirmed

    async def assemble_stories(self, chat_id: int, now: int, *,
                               pipeline_run_id=None) -> int:
        """Сборка историй (D7): компоненты связности по confirmed-связям;
        новая версия при каждом изменении; повторы без роста независимости;
        противоречие фиксируется, не разрешается молча; unknown →
        `uncertain`/«исход неизвестен». Возврат — число противоречий."""
        episodes = await self.repo.list_episodes(chat_id, limit=400)
        by_id = {str(e["episode_id"]): e for e in episodes}
        continuations = await self.repo.list_continuations(list(by_id))
        confirmed: set[frozenset[str]] = set()
        for link in continuations:
            if str(link.get("status")) != "confirmed":
                continue
            confirmed.add(frozenset((str(link["from_episode_id"]),
                                     str(link["to_episode_id"]))))
        parent = {eid: eid for eid in by_id}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[max(ra, rb)] = min(ra, rb)

        for pair in confirmed:
            a, b = tuple(pair)
            if a in parent and b in parent:
                union(a, b)
        components: dict[str, list[str]] = {}
        for eid in by_id:
            components.setdefault(find(eid), []).append(eid)
        contradictions = 0
        for members in components.values():
            members = sorted(members)[:_STORY_EPS_CAP]
            member_rows = [by_id[eid] for eid in members if eid in by_id]
            if not member_rows:
                continue
            events_start = [int(r["event_start_ts"]) for r in member_rows
                            if r.get("event_start_ts")]
            events_end = [int(r["event_end_ts"]) for r in member_rows
                          if r.get("event_end_ts")]
            participants: list[str] = []
            for row in member_rows:
                for pid in _json_loads(row.get("participants_json"), []):
                    if pid not in participants:
                        participants.append(pid)
            raw_claims: list[dict] = []
            for row in member_rows:
                for claim in _json_loads(row.get("claims_json"), []):
                    raw_claims.append({
                        "text": str(claim.get("text") or ""),
                        "refs": list(claim.get("refs") or ()),
                    })
            claims, _repeats = merge_claims(raw_claims)
            conflicts = detect_contradictions(claims)
            if conflicts:
                contradictions += len(conflicts)
                emit_story_event(
                    "contradiction_found", outcome="success",
                    chat_id=chat_id, episode_ids=members,
                    summary=f"conflicts:{len(conflicts)}",
                    reason_code="story_contradiction_found", stage="assemble",
                    event_start=(min(events_start) if events_start
                                 else None),
                    event_end=(max(events_end) if events_end else None),
                    discovered_at=now, participants=participants,
                    pipeline_run_id=pipeline_run_id)
            known_outcomes = [r for r in member_rows
                              if r.get("outcome") and r.get(
                                  "outcome") != EPISODE_UNKNOWN_OUTCOME]
            if known_outcomes:
                outcome = known_outcomes[0]["outcome"]
                state = "open"
            else:
                # §9.1: неизвестный исход — «исход неизвестен», финал не
                # выдумывается.
                outcome = EPISODE_UNKNOWN_OUTCOME
                state = "uncertain"
            verification = "tentative" if conflicts else "unknown"
            title = (member_rows[0].get("title")
                     or (f"История {min(events_start)}" if events_start
                         else f"История {now}"))
            summary = " ".join(
                str(r.get("summary") or "") for r in member_rows
                if r.get("summary"))[:2000]
            existing_story = None
            for candidate_row in member_rows:
                story_ids = await self.repo.story_ids_for_episode(
                    candidate_row["episode_id"])
                if story_ids:
                    existing_story = await self.repo.get_story(story_ids[0])
                    if existing_story is not None:
                        break
            if existing_story is not None:
                # Повторная сборка создаёт новую версию только при
                # изменении (no-op rebuild не спамит версиями). Поля под
                # ручным override пересборка не меняет эффективно — в
                # сравнении не участвуют (A13).
                card = effective_story(existing_story)
                current_eps = set(await self.repo.story_episode_ids(
                    existing_story["story_id"]))
                unchanged = current_eps == set(members)
                if unchanged:
                    for field, desired in (("title", title),
                                           ("summary", summary),
                                           ("outcome", outcome),
                                           ("state", state),
                                           ("verification", verification)):
                        if existing_story.get(f"override_{field}"):
                            continue
                        if str(card.get(field) or "") != str(desired or ""):
                            unchanged = False
                            break
                if unchanged:
                    continue
            try:
                story_id, _version_id, created = await self.repo.upsert_story(
                    chat_id=chat_id, title=title, summary=summary,
                    participants=participants, claims=claims,
                    event_start=(min(events_start) if events_start
                                 else None),
                    event_end=(max(events_end) if events_end else None),
                    outcome=outcome, state=state, verification=verification,
                    open_questions=[], episode_ids=members,
                    extractor_version=EXTRACTOR_VERSION, now=now,
                    discovered_at=now)
            except Exception:
                logger.warning("[mca05] story assemble failed",
                               exc_info=True)
                continue
            if not story_id:
                continue
            await record_story_provenance(
                self._db, chat_id=chat_id, story_id=story_id,
                episode_ids=members, extractor_version=EXTRACTOR_VERSION)
            if created:
                emit_story_event(
                    "story_discovered",
                    outcome="success", chat_id=chat_id, story_id=story_id,
                    episode_ids=members,
                    event_start=(min(events_start) if events_start
                                 else None),
                    event_end=(max(events_end) if events_end else None),
                    discovered_at=now, participants=participants,
                    summary=summary[:200], stage="assemble",
                    pipeline_run_id=pipeline_run_id)
            elif not (existing_story is not None and set(
                    await self.repo.story_episode_ids(story_id))
                    >= set(members)):
                # Состав эпизодов расширился.
                emit_story_event(
                    "story_extended",
                    outcome="success", chat_id=chat_id, story_id=story_id,
                    episode_ids=members,
                    event_start=(min(events_start) if events_start
                                 else None),
                    event_end=(max(events_end) if events_end else None),
                    discovered_at=now, participants=participants,
                    summary=summary[:200], stage="assemble",
                    pipeline_run_id=pipeline_run_id)
            else:
                # Повторная сборка без изменения состава (изменились
                # поля/версия) — контракт §16.1 story_rebuilt.
                emit_story_event(
                    "story_rebuilt",
                    outcome="success", chat_id=chat_id, story_id=story_id,
                    episode_ids=members,
                    event_start=(min(events_start) if events_start
                                 else None),
                    event_end=(max(events_end) if events_end else None),
                    discovered_at=now, participants=participants,
                    summary=summary[:200], stage="assemble",
                    pipeline_run_id=pipeline_run_id)
        return contradictions
