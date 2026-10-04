"""MCA-08 (ADR-1028-11 D3–D5, T-4903…T-4905) — scoped-просьбы по стилю/темам.

Единственный механизм (spec §5.2): одна таблица `mca_style_requests` (v26),
один сервис. Второго хранилища/словаря/резолвера нет: `user_prefs.tone_preset`
(temperature) и `/tone` не дублируются и не мигрируются.

**Explicit-only.** Две двери — один writer:
  1. скрытая команда `/style` (прецедент `/tone`; в меню `bot_commands.py` НЕ
     регистрируется);
  2. закрытая грамматика «фраза-директива + scope-маркер» в сообщениях,
     адресованных боту (вход обрабатывается до сборки контекста).
Молчание, отсутствие реакции, шутка, провокация, число ответов/конфликтов —
никогда не создают, не усиливают и не отменяют просьбу (анти-максимизация;
тест-инвариант обязателен — T-4905).

**Права (fail-closed):** participant — сам автор; chat/topic — админ
(`chat_access.is_admin` ИЛИ `chat_lore_store.is_chat_admin`); ошибка проверки
→ отказ (`style_request_denied`), запись не создаётся.

**Приоритет (D5):** participant > topic > chat; внутри одного scope/facet —
последняя по `(created_at, id)`; проигравшие не рендерятся (LLM-слияния нет).
Ядро владельца выше любой просьбы (§3).

Kill-switch **K3** `MCA_STYLE_SCOPE_ENABLED` (env-only, default ON): OFF → нет
ingestion/прав/резолва/команды; таблица не читается/не пишется (байт-паритет
2.58.54). Env-only TTL: chat `MCA_STYLE_SCOPE_CHAT_TTL_DAYS` (7), topic
`MCA_STYLE_SCOPE_TOPIC_TTL_DAYS` (30); participant — без срока.

R17: в журналы/события — только ID/коды/числа. `topic_key` хранится в БД как
условие темы и попадает в prompt-блок/ответ команды (данные, не журнал);
сырой текст сообщений и label в события не пишутся.
"""
from __future__ import annotations

import dataclasses
import logging
import re
import time

from services import mca_gates
from services.summary_xml import escape_xml_text

logger = logging.getLogger(__name__)

# ── закрытые наборы (канон §5.3/§5.4) ───────────────────────────────────────

SCOPE_PARTICIPANT = "participant"
SCOPE_CHAT = "chat"
SCOPE_TOPIC = "topic"

FACET_ORDER = ("verbosity", "humor", "emoji", "directness", "address")

# facet → directive → канон-текст (серверный; пользовательский текст не
# хранится). Единственный словарь директив (второй запрещён).
DIRECTIVE_CANON: dict[tuple[str, str], str] = {
    ("verbosity", "short"): "отвечай короче",
    ("verbosity", "long"): "отвечай подробнее",
    ("humor", "off"): "без шуток",
    ("humor", "on"): "можно шутить",
    ("emoji", "off"): "без смайлов",
    ("directness", "direct"): "говори прямо, без смягчений",
    ("directness", "soft"): "формулируй мягче",
    ("address", "ty"): "обращайся на «ты»",
    ("address", "vy"): "обращайся на «вы»",
}

_SCOPE_TAGS = {
    SCOPE_PARTICIPANT: "[участник]",
    SCOPE_CHAT: "[чат]",
}

# Бюджеты (константы кода; §5.2): активных строк/час-принятых записей.
MAX_ACTIVE_PER_CHAT = 20
MAX_ACTIVE_PER_PARTICIPANT = 5
MAX_ACCEPTED_PER_HOUR = 5
SWEEP_EVENT_LIMIT = 5
MAX_LIST_LINES = 10
RENDER_CAP = 600

TOPIC_KEY_RE = re.compile(r"^[0-9a-zа-яё _-]{2,48}$")

_HOUR_SECONDS = 3600.0

# ── детерминированный ингест (закрытая грамматика; без LLM) ─────────────────
# Работаем по нормализованному тексту: casefold, ё→е, сжатие пробелов.

_WHITESPACE_RE = re.compile(r"\s+")
_BOT_ADDRESS_RE = re.compile(
    r"(?:@[a-z0-9_]+|\bбот(?:ик|яра|охуета|охуйня)?\b)")
_PUNCT = "—–,;.!?()«»\"'"
_TOPIC_MARKER_RE = re.compile(
    r"(?:по\s+теме|когда\s+речь\s+о|если\s+разговор\s+о|когда\s+про)\s+")
_CHAT_MARKER_RE = re.compile(r"(?:в\s+этом\s+чате|для\s+всех|воо?бще|тут)")
_PARTICIPANT_MARKER_RE = re.compile(r"(?:со\s+мной|для\s+меня|\bмне\b)")

# (facet, directive, patterns) — закрытый набор формулировок (§5.3).
_DIRECTIVE_PATTERNS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    ("verbosity", "short", (
        r"(?:отвечай|пиши|говори|ответь)\s+(?:короче|кратко|покороче)",)),
    ("verbosity", "long", (
        r"(?:отвечай|пиши|говори|ответь)\s+"
        r"(?:подробнее|подробней|длиннее|длинно|побольше|больше)",)),
    ("humor", "off", (
        r"без\s+шуток", r"\bне\s+шути\b", r"без\s+юмора", r"не\s+заигрывай")),
    ("humor", "on", (
        r"можно\s+шутить", r"можешь\s+шутить", r"(?<!не )\bшути\b")),
    ("emoji", "off", (
        r"без\s+(?:смайл\w*|эмодзи|эмоджей|эмоджи)",
        r"не\s+используй\s+(?:смайл\w*|эмодзи)",)),
    ("directness", "direct", (
        r"говори\s+прямо", r"без\s+смягчени\w*", r"не\s+смягчай")),
    ("directness", "soft", (
        r"формулируй\s+мягче", r"говори\s+мягче", r"\bпомягче\b")),
    ("address", "ty", (
        r"обращайся\s+на\s*[«\"']?ты", r"\bна\s+ты\b")),
    ("address", "vy", (
        r"обращайся\s+на\s*[«\"']?вы", r"\bна\s+вы\b")),
)

_DIRECTIVE_COMPILED = tuple(
    (facet, directive, tuple(re.compile(p) for p in patterns))
    for facet, directive, patterns in _DIRECTIVE_PATTERNS
)

# Fillers: слова, не делающие фразу не-директивой (вежливость/связки).
_FILLER_TOKENS = frozenset({
    "пожалуйста", "плиз", "ну", "да", "и", "а", "же", "это", "вот", "ка",
    "можно", "будь", "добр", "добра", "старайся", "старайс", "пж",
})
_RESIDUAL_TOKEN_RE = re.compile(r"[0-9a-zа-яё]+")


def _normalize(text: str) -> str:
    """casefold + ё→е + сжатие пробелов (детерминированная нормализация)."""
    value = str(text or "").casefold().replace("ё", "е")
    return _WHITESPACE_RE.sub(" ", value).strip()


def _strip_bot_address(text: str) -> str:
    return _WHITESPACE_RE.sub(" ", _BOT_ADDRESS_RE.sub(" ", text)).strip()


def _directive_matches(text: str) -> list[tuple[str, str, tuple[int, int]]]:
    """Все уникальные (facet, directive) с первым span'ом совпадения."""
    result: list[tuple[str, str, tuple[int, int]]] = []
    for facet, directive, patterns in _DIRECTIVE_COMPILED:
        for pattern in patterns:
            match = pattern.search(text)
            if match:
                result.append((facet, directive, (match.start(), match.end())))
                break
    return result


def _residual_ok(residual: str) -> bool:
    """После вырезания директивы/маркеров остались только fillers?"""
    for token in _RESIDUAL_TOKEN_RE.findall(residual):
        if token not in _FILLER_TOKENS:
            return False
    return True


def _topic_label(cleaned: str, marker: re.Match, spans: tuple[int, int]
                 ) -> str:
    """Метка темы — между маркером и директивой/пунктуацией/концом."""
    start = marker.end()
    end = len(cleaned)
    if spans[0] > start:
        end = min(end, spans[0])
    for index in range(start, end):
        if cleaned[index] in _PUNCT:
            end = index
            break
    label = cleaned[start:end].strip(_PUNCT + " ")
    return _WHITESPACE_RE.sub(" ", label)


def validate_topic_key(label: str) -> str | None:
    """Нормализованная метка темы или None (закрытая грамматика §5.2)."""
    try:
        key = _WHITESPACE_RE.sub(" ", str(label or "").casefold().strip())
    except Exception:      # pragma: no cover - защитная ветка
        return None
    try:
        key = key.replace("ё", "е")
        if TOPIC_KEY_RE.match(key):
            return key
    except Exception:      # pragma: no cover - защитная ветка
        return None
    return None


@dataclasses.dataclass(frozen=True)
class ParsedRequest:
    """Результат закрытой грамматики (R17-safe: только коды/метка)."""

    facet: str
    directive: str
    scope: str
    topic_key: str | None = None
    ambiguous: bool = False


def parse_directive_request(text: str) -> ParsedRequest | None:
    """Разобрать сообщение как просьбу. None — не похоже (без событий)."""
    try:
        cleaned = _strip_bot_address(_normalize(text))
        if not cleaned:
            return None
        matches = _directive_matches(cleaned)
        if not matches:
            return None
        if len(matches) != 1:
            # Несколько директив в одном сообщении — вид неоднозначен.
            facet, directive, _span = matches[0]
            return ParsedRequest(facet, directive,
                                 SCOPE_PARTICIPANT, ambiguous=True)
        facet, directive, span = matches[0]

        topic_markers = list(_TOPIC_MARKER_RE.finditer(cleaned))
        chat_present = bool(_CHAT_MARKER_RE.search(cleaned))
        participant_present = bool(_PARTICIPANT_MARKER_RE.search(cleaned))
        if len(topic_markers) > 1:
            return ParsedRequest(facet, directive, SCOPE_PARTICIPANT,
                                 ambiguous=True)
        if topic_markers:
            if chat_present or participant_present:
                return ParsedRequest(facet, directive, SCOPE_PARTICIPANT,
                                     ambiguous=True)
            marker = topic_markers[0]
            label = _topic_label(cleaned, marker, span)
            key = validate_topic_key(label)
            if key is None:
                return ParsedRequest(facet, directive, SCOPE_PARTICIPANT,
                                     ambiguous=True)
            residual = cleaned[:span[0]] + " " + cleaned[span[1]:]
            residual = residual.replace(
                cleaned[marker.start():marker.end()], " ")
            residual = residual.replace(label, " ", 1)
            if not _residual_ok(residual):
                return ParsedRequest(facet, directive, SCOPE_PARTICIPANT,
                                     ambiguous=True)
            return ParsedRequest(facet, directive, SCOPE_TOPIC, topic_key=key)
        if chat_present and participant_present:
            return ParsedRequest(facet, directive, SCOPE_PARTICIPANT,
                                 ambiguous=True)
        scope = SCOPE_CHAT if chat_present else SCOPE_PARTICIPANT
        residual = cleaned[:span[0]] + " " + cleaned[span[1]:]
        if scope == SCOPE_CHAT:
            residual = _CHAT_MARKER_RE.sub(" ", residual)
        else:
            residual = _PARTICIPANT_MARKER_RE.sub(" ", residual)
        if not _residual_ok(residual):
            return ParsedRequest(facet, directive, SCOPE_PARTICIPANT,
                                 ambiguous=True)
        return ParsedRequest(facet, directive, scope)
    except Exception:      # pragma: no cover - защитная ветка (fail-open)
        logger.debug("[mca08_style] parse failed", exc_info=True)
        return None


def parse_directive_only(text: str) -> tuple[str, str] | None:
    """Для команды: ровно одна директива, без scope-маркеров и мусора."""
    try:
        cleaned = _strip_bot_address(_normalize(text))
        matches = _directive_matches(cleaned)
        if len(matches) != 1:
            return None
        facet, directive, span = matches[0]
        residual = cleaned[:span[0]] + " " + cleaned[span[1]:]
        if not _residual_ok(residual):
            return None
        return facet, directive
    except Exception:      # pragma: no cover - защитная ветка
        return None


# ── резолвер/рендер (D5) ────────────────────────────────────────────────────

def _topic_matches(topic_key: str, text: str) -> bool:
    """Все токены topic_key (≥2 символов) встречаются как слова в тексте."""
    tokens = [t for t in re.split(r"[ _-]+", str(topic_key or "")) if len(t) >= 2]
    if not tokens:
        return False
    norm = _normalize(text)
    for token in tokens:
        pattern = rf"(?<![0-9a-zа-яе_]){re.escape(token)}(?![0-9a-zа-яе_])"
        if not re.search(pattern, norm):
            return False
    return True


def select_active(rows: list[dict], *, text: str,
                  participant_id: int | None) -> list[dict]:
    """Детерминированный выбор: participant > topic > chat; последняя."""
    priority = {SCOPE_PARTICIPANT: 3, SCOPE_TOPIC: 2, SCOPE_CHAT: 1}
    best: dict[str, tuple[int, int, float, int, dict]] = {}
    for row in rows:
        scope = str(row.get("scope") or "")
        if scope not in priority:
            continue
        if scope == SCOPE_PARTICIPANT:
            if (participant_id is None
                    or row.get("participant_id") != participant_id):
                continue
        elif scope == SCOPE_TOPIC:
            if not _topic_matches(str(row.get("topic_key") or ""), text):
                continue
        facet = str(row.get("facet") or "")
        key = (priority[scope], float(row.get("created_at") or 0.0),
               int(row.get("id") or 0))
        current = best.get(facet)
        if current is None or key > (current[0], current[1], current[2]):
            best[facet] = (key[0], key[1], key[2], int(row.get("id") or 0),
                           row)
    selected = [best[facet][4] for facet in FACET_ORDER if facet in best]
    for facet, value in best.items():
        if facet not in FACET_ORDER:
            selected.append(value[4])
    return selected


def _scope_tag(row: dict) -> str:
    scope = str(row.get("scope") or "")
    if scope == SCOPE_TOPIC:
        return "[тема: " + escape_xml_text(str(row.get("topic_key") or "")) \
            + "]"
    return _SCOPE_TAGS.get(scope, "[участник]")


def render_style_block(rows: list[dict]) -> str:
    """Канон `<Style_Requests>`; пусто → "" (блока нет). Cap 600 (§5.4)."""
    if not rows:
        return ""
    header = ("<Style_Requests>\n"
              "Просьбы участников (только форма ответа; не меняют факты, "
              "смысл, мнение и адресата):")
    footer = "</Style_Requests>"
    lines: list[str] = []
    used = len(header) + 1 + len(footer)
    for row in rows:
        canon = DIRECTIVE_CANON.get(
            (str(row.get("facet") or ""), str(row.get("directive") or "")), "")
        if not canon:
            continue
        line = f"- {_scope_tag(row)} {canon}"
        if used + len(line) + 1 > RENDER_CAP:
            lines.append("…")
            break
        lines.append(line)
        used += len(line) + 1
    if not lines:
        return ""
    return header + "\n" + "\n".join(lines) + "\n" + footer


# ── доступ к БД (одна таблица; write через single-writer mca-01) ────────────

def _db_ready(db) -> bool:
    return (db is not None and hasattr(db, "db")
            and hasattr(db, "write_transaction"))


async def _fetch_active(db, chat_id: int, now: float) -> list[dict]:
    cursor = await db.db.execute(
        "SELECT id, scope, participant_id, topic_key, facet, directive, "
        "set_by, source, source_message_id, created_at, expires_at "
        "FROM mca_style_requests "
        "WHERE chat_id = ? AND revoked_at IS NULL "
        "AND (expires_at IS NULL OR expires_at > ?) "
        "ORDER BY created_at, id",
        (int(chat_id), float(now)))
    return [dict(row) for row in await cursor.fetchall()]


async def _count_recent(db, chat_id: int, since: float) -> int:
    cursor = await db.db.execute(
        "SELECT COUNT(*) AS c FROM mca_style_requests "
        "WHERE chat_id = ? AND created_at >= ?",
        (int(chat_id), float(since)))
    row = await cursor.fetchone()
    return int(row["c"] if row is not None else 0)


async def _has_chat_admin_rights(user_id: int, chat_id: int) -> bool:
    """chat/topic-scope: админ или чат-админ; ошибка → False (fail-closed)."""
    try:
        from services import chat_access
        if chat_access.is_admin(int(user_id)):
            return True
    except Exception:
        return False
    try:
        from services import lore_runtime
        store = lore_runtime.get_lore_store()
        if store is None:
            return False
        return bool(await store.is_chat_admin(int(user_id), int(chat_id)))
    except Exception:
        return False


def _expires_at(scope: str, now: float) -> float | None:
    if scope == SCOPE_CHAT:
        return now + mca_gates.style_scope_chat_ttl_days() * 86400.0
    if scope == SCOPE_TOPIC:
        return now + mca_gates.style_scope_topic_ttl_days() * 86400.0
    return None


def _emit(reason_code: str, *, chat_id: int, level: str | None = None,
          **fields) -> None:
    """Notable-событие `style_scope` (R17-safe; fail-open)."""
    try:
        from services.mca_events import LEVEL_INFO, LEVEL_WARN, emit_mca_event
        if level is None:
            level = (LEVEL_WARN if reason_code == "style_request_denied"
                     else LEVEL_INFO)
        emit_mca_event(
            "style_scope",
            outcome=("success" if reason_code in (
                "style_request_recorded", "style_request_superseded",
                "style_request_expired") else "skipped"),
            level=level, component="style_scope", reason_code=reason_code,
            chat_id=int(chat_id), **fields)
    except Exception:      # fail-open: событие не рвёт поток
        return


async def _apply_request(db, *, chat_id: int, set_by: int,
                         parsed: ParsedRequest | None,
                         source: str, source_message_id: int | None,
                         now: float | None = None) -> dict | None:
    """Единая точка записи (обе двери → этот writer)."""
    if parsed is None:
        return None
    if parsed.ambiguous:
        _emit("style_request_ambiguous_skipped", chat_id=chat_id)
        return {"status": "ambiguous_skipped"}
    if parsed.scope in (SCOPE_CHAT, SCOPE_TOPIC):
        if not await _has_chat_admin_rights(set_by, chat_id):
            _emit("style_request_denied", chat_id=chat_id)
            return {"status": "denied"}
    if parsed.scope == SCOPE_TOPIC and parsed.topic_key is None:
        _emit("style_request_ambiguous_skipped", chat_id=chat_id)
        return {"status": "ambiguous_skipped"}
    now = float(now if now is not None else time.time())
    try:
        active = await _fetch_active(db, chat_id, now)
        per_participant = sum(
            1 for row in active
            if row.get("scope") == SCOPE_PARTICIPANT
            and row.get("participant_id") == set_by)
        recent = await _count_recent(db, chat_id, now - _HOUR_SECONDS)
    except Exception:
        logger.warning("[mca08_style] budget read failed — write skipped | "
                       "chat=%s", chat_id, exc_info=True)
        return None
    if (len(active) >= MAX_ACTIVE_PER_CHAT
            or per_participant >= MAX_ACTIVE_PER_PARTICIPANT
            or recent >= MAX_ACCEPTED_PER_HOUR):
        logger.warning("[mca08_style] budget exceeded — refused | chat=%s | "
                       "scope=%s", chat_id, parsed.scope)
        return {"status": "budget_exceeded"}
    try:
        await sweep_expired(db, chat_id=chat_id, now=now)
    except Exception:
        logger.debug("[mca08_style] sweep failed — continue", exc_info=True)

    participant_id = set_by if parsed.scope == SCOPE_PARTICIPANT else None
    topic_key = parsed.topic_key if parsed.scope == SCOPE_TOPIC else None
    params = (int(chat_id), parsed.scope, participant_id, topic_key,
              parsed.facet, parsed.directive, int(set_by), source,
              source_message_id, now, _expires_at(parsed.scope, now))

    async def _body(conn):
        cursor = await conn.execute(
            "INSERT INTO mca_style_requests (chat_id, scope, participant_id, "
            "topic_key, facet, directive, set_by, source, source_message_id, "
            "created_at, expires_at, revoked_at, superseded_by) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,NULL,NULL)", params)
        new_id = int(cursor.lastrowid)
        revoke = await conn.execute(
            "UPDATE mca_style_requests SET revoked_at = ?, superseded_by = ? "
            "WHERE chat_id = ? AND id <> ? AND revoked_at IS NULL "
            "AND scope = ? AND facet = ? AND participant_id IS ? "
            "AND topic_key IS ?",
            (now, new_id, int(chat_id), new_id, parsed.scope, parsed.facet,
             participant_id, topic_key))
        superseded = int(revoke.rowcount or 0)
        return new_id, superseded

    try:
        new_id, superseded = await db.write_transaction(
            _body, op_name="mca_style_request")
    except Exception:
        logger.warning("[mca08_style] write failed | chat=%s | scope=%s",
                       chat_id, parsed.scope, exc_info=True)
        return None
    fields = {"entity_id": new_id}
    if source_message_id is not None:
        fields["message_id"] = int(source_message_id)
    _emit("style_request_recorded", chat_id=chat_id, **fields)
    if superseded:
        _emit("style_request_superseded", chat_id=chat_id, entity_id=new_id)
    logger.info("[mca08_style] recorded | chat=%s scope=%s facet=%s "
                "source=%s superseded=%d", chat_id, parsed.scope,
                parsed.facet, source, superseded)
    return {"status": "recorded", "id": new_id,
            "facet": parsed.facet, "directive": parsed.directive,
            "scope": parsed.scope, "topic_key": topic_key,
            "superseded": superseded}


async def ingest_message(db, *, chat_id: int, sender_id: int, text: str,
                         message_id: int | None = None,
                         now: float | None = None) -> dict | None:
    """Ингест из сообщения (закрытая грамматика; K3 OFF → no-op)."""
    if not mca_gates.style_scope_enabled() or not _db_ready(db):
        return None
    parsed = parse_directive_request(text)
    if parsed is None:
        return None
    return await _apply_request(
        db, chat_id=int(chat_id), set_by=int(sender_id), parsed=parsed,
        source="message", source_message_id=message_id, now=now)


async def sweep_expired(db, *, chat_id: int, now: float | None = None,
                        limit: int = SWEEP_EVENT_LIMIT) -> int:
    """Bounded write-time sweep: пометить истёкшие (≤5 событий за sweep)."""
    if not mca_gates.style_scope_enabled() or not _db_ready(db):
        return 0
    now = float(now if now is not None else time.time())
    cap = max(1, int(limit))

    async def _body(conn):
        cursor = await conn.execute(
            "SELECT id FROM mca_style_requests WHERE chat_id = ? "
            "AND revoked_at IS NULL AND expires_at IS NOT NULL "
            "AND expires_at <= ? ORDER BY id LIMIT ?",
            (int(chat_id), now, cap))
        ids = [int(row[0]) for row in await cursor.fetchall()]
        if ids:
            marks = ",".join("?" for _ in ids)
            await conn.execute(
                f"UPDATE mca_style_requests SET revoked_at = ? "
                f"WHERE id IN ({marks})", (now, *ids))
        return ids

    try:
        ids = await db.write_transaction(_body, op_name="mca_style_expire")
    except Exception:
        logger.debug("[mca08_style] expire sweep failed", exc_info=True)
        return 0
    for row_id in ids or []:
        _emit("style_request_expired", chat_id=chat_id, entity_id=row_id)
    return len(ids or [])


async def reset_requests(db, *, chat_id: int, scope: str | None = None,
                         participant_id: int | None = None,
                         topic_key: str | None = None,
                         now: float | None = None) -> int:
    """Сброс (идемпотентный): revoke совпавших активных строк."""
    if not mca_gates.style_scope_enabled() or not _db_ready(db):
        return 0
    now = float(now if now is not None else time.time())
    clauses = ["chat_id = ?", "revoked_at IS NULL"]
    params: list = [int(chat_id)]
    if scope is not None:
        clauses.append("scope = ?")
        params.append(str(scope))
        if scope == SCOPE_PARTICIPANT:
            clauses.append("participant_id IS ?")
            params.append(participant_id)
        elif scope == SCOPE_TOPIC:
            clauses.append("topic_key IS ?")
            params.append(topic_key)

    async def _body(conn):
        cursor = await conn.execute(
            f"UPDATE mca_style_requests SET revoked_at = ? "
            f"WHERE {' AND '.join(clauses)}", (now, *params))
        return int(cursor.rowcount or 0)

    try:
        removed = int(await db.write_transaction(
            _body, op_name="mca_style_reset") or 0)
    except Exception:
        logger.warning("[mca08_style] reset failed | chat=%s | scope=%s",
                       chat_id, scope, exc_info=True)
        return 0
    if removed:
        logger.info("[mca08_style] reset | chat=%s scope=%s removed=%d",
                    chat_id, scope or "all", removed)
    return removed


async def resolve_active(db, *, chat_id: int, text: str,
                         participant_id: int | None,
                         now: float | None = None) -> list[dict]:
    """Активные просьбы, выбранные для текущего ответа (приоритет D5)."""
    if not mca_gates.style_scope_enabled() or not _db_ready(db):
        return []
    now = float(now if now is not None else time.time())
    try:
        rows = await _fetch_active(db, chat_id, now)
    except Exception:
        logger.debug("[mca08_style] resolve read failed", exc_info=True)
        return []
    return select_active(rows, text=str(text or ""),
                         participant_id=participant_id)


async def resolve_block(db, *, chat_id: int, text: str,
                        participant_id: int | None,
                        now: float | None = None) -> str:
    """Готовый prompt-блок `<Style_Requests>` (пусто → "")."""
    rows = await resolve_active(db, chat_id=chat_id, text=text,
                                participant_id=participant_id, now=now)
    return render_style_block(rows)


# ── команда /style (скрытая; прецедент /tone) ───────────────────────────────

async def handle_command(db, *, chat_id: int, user_id: int, args: str,
                         now: float | None = None) -> str | None:
    """Канон-фраза ответа; None → команда неактивна (K3 OFF → UNHANDLED)."""
    from services import smartmodule_phrases as _phrases
    if not mca_gates.style_scope_enabled():
        return None
    if not _db_ready(db):
        return _phrases.CHAT_STYLE_UNAVAILABLE_PHRASE
    try:
        return await _handle_command(db, chat_id=int(chat_id),
                                     user_id=int(user_id), args=str(args or ""),
                                     now=now)
    except Exception:
        logger.warning("[mca08_style] command failed | chat=%s user=%s",
                       chat_id, user_id, exc_info=True)
        return _phrases.CHAT_STYLE_UNAVAILABLE_PHRASE


async def _handle_command(db, *, chat_id: int, user_id: int, args: str,
                          now: float | None) -> str:
    from services import smartmodule_phrases as _phrases
    raw = " ".join(str(args or "").split())
    low = raw.casefold()
    if not raw or low in ("список", "list"):
        return await _list_phrase(db, chat_id=chat_id, now=now)
    if low == "off":
        await reset_requests(db, chat_id=chat_id, scope=SCOPE_PARTICIPANT,
                             participant_id=user_id, now=now)
        return _phrases.CHAT_STYLE_OFF_DONE_PHRASE
    if low in ("всё off", "все off"):
        if not await _has_chat_admin_rights(user_id, chat_id):
            _emit("style_request_denied", chat_id=chat_id)
            return _phrases.CHAT_STYLE_ADMIN_ONLY_PHRASE
        await reset_requests(db, chat_id=chat_id, now=now)
        return _phrases.CHAT_STYLE_OFF_ALL_DONE_PHRASE
    if low.startswith("чат "):
        if not await _has_chat_admin_rights(user_id, chat_id):
            _emit("style_request_denied", chat_id=chat_id)
            return _phrases.CHAT_STYLE_ADMIN_ONLY_PHRASE
        rest = raw[4:].strip()
        if rest.casefold() == "off":
            await reset_requests(db, chat_id=chat_id, scope=SCOPE_CHAT,
                                 now=now)
            return _phrases.CHAT_STYLE_OFF_CHAT_DONE_PHRASE
        parsed = parse_directive_only(rest)
        if parsed is None:
            return _phrases.CHAT_STYLE_UNKNOWN_PHRASE
        facet, directive = parsed
        result = await _apply_request(
            db, chat_id=chat_id, set_by=user_id,
            parsed=ParsedRequest(facet, directive, SCOPE_CHAT),
            source="command", source_message_id=None, now=now)
        if result is None or result.get("status") != "recorded":
            return _phrases.CHAT_STYLE_UNAVAILABLE_PHRASE
        return _phrases.CHAT_STYLE_SET_CHAT_PHRASE.replace(
            "{directive}", DIRECTIVE_CANON[(facet, directive)])
    if low.startswith("тема "):
        if not await _has_chat_admin_rights(user_id, chat_id):
            _emit("style_request_denied", chat_id=chat_id)
            return _phrases.CHAT_STYLE_ADMIN_ONLY_PHRASE
        rest = raw[5:].strip()
        parts = rest.split(None, 1)
        if not parts:
            return _phrases.CHAT_STYLE_UNKNOWN_PHRASE
        label = validate_topic_key(parts[0])
        if label is None:
            return _phrases.CHAT_STYLE_INVALID_TOPIC_PHRASE
        if len(parts) == 1 or parts[1].strip().casefold() == "off":
            await reset_requests(db, chat_id=chat_id, scope=SCOPE_TOPIC,
                                 topic_key=label, now=now)
            return _phrases.CHAT_STYLE_OFF_TOPIC_DONE_PHRASE.replace(
                "{label}", label)
        parsed = parse_directive_only(parts[1])
        if parsed is None:
            return _phrases.CHAT_STYLE_UNKNOWN_PHRASE
        facet, directive = parsed
        result = await _apply_request(
            db, chat_id=chat_id, set_by=user_id,
            parsed=ParsedRequest(facet, directive, SCOPE_TOPIC,
                                 topic_key=label),
            source="command", source_message_id=None, now=now)
        if result is None or result.get("status") != "recorded":
            return _phrases.CHAT_STYLE_UNAVAILABLE_PHRASE
        return (_phrases.CHAT_STYLE_SET_TOPIC_PHRASE
                .replace("{directive}", DIRECTIVE_CANON[(facet, directive)])
                .replace("{label}", label))
    phrase = raw
    if low.startswith("со мной "):
        phrase = raw[len("со мной "):].strip()
    parsed = parse_directive_only(phrase)
    if parsed is None:
        return _phrases.CHAT_STYLE_UNKNOWN_PHRASE
    facet, directive = parsed
    result = await _apply_request(
        db, chat_id=chat_id, set_by=user_id,
        parsed=ParsedRequest(facet, directive, SCOPE_PARTICIPANT),
        source="command", source_message_id=None, now=now)
    if result is None or result.get("status") != "recorded":
        return _phrases.CHAT_STYLE_UNAVAILABLE_PHRASE
    return _phrases.CHAT_STYLE_SET_PARTICIPANT_PHRASE.replace(
        "{directive}", DIRECTIVE_CANON[(facet, directive)])


async def _list_phrase(db, *, chat_id: int, now: float | None) -> str:
    from services import smartmodule_phrases as _phrases
    rows = await _fetch_active(db, chat_id,
                               float(now if now is not None else time.time()))
    if not rows:
        return _phrases.CHAT_STYLE_LIST_EMPTY_PHRASE
    lines = []
    for row in rows[:MAX_LIST_LINES]:
        canon = DIRECTIVE_CANON.get(
            (str(row.get("facet") or ""), str(row.get("directive") or "")), "")
        if canon:
            lines.append(f"- {_scope_tag(row)} {canon}")
    if not lines:
        return _phrases.CHAT_STYLE_LIST_EMPTY_PHRASE
    if len(rows) > MAX_LIST_LINES:
        lines.append("…")
    return _phrases.CHAT_STYLE_LIST_HEADER + "\n" + "\n".join(lines)
