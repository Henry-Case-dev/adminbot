"""Раунд 10.14 (F2 persona-storage-core, ADR-1014-1) — личность БОТА.

ВАЖНО (naming): это личность БОТА (`personas`/`persona_traits` в PG).
Существующие `build_persona_card`/`get_persona_card`/«досье» — карточка
ПОЛЬЗОВАТЕЛЯ (F8 10.13) — НЕ ТРОГАЮТСЯ.

Хранилище (PG):
  * `personas` — статические поля (name/biography/system_prompt_overrides/
    is_aware_ai) со scope first-class (`is_global` + `chat_id`);
  * `persona_traits` — динамические черты характера (пишет «Глубокий сон»).

Резолв scope: per-chat строка → global строка → `BotPersona.empty()`.
Fail-open: PG down/ошибка → пустая персона (промпт деградирует к прежнему
поведению байт-в-байт, spec §3.2/F2-Q5).

Промпт-блок дописывается ХВОСТОМ системного промпта direct-чата
(`system_prompt + "\n\n" + block`); при `is_aware_ai=false` после `</Persona>`
идёт жёсткий запрет `_NO_AI_DISCLOSURE_BLOCK` (fail-safe: бот не признаёт
ИИ-природу).
"""
import dataclasses
import datetime
import logging

from config.settings import settings
from services import hot_config as hot

logger = logging.getLogger(__name__)

# Hard prohibition (spec §3.1, ADR-1014-1 §2): при is_aware_ai=false —
# дописывается ПОСЛЕ </Persona>. Текст — канон из spec §3.1.
_NO_AI_DISCLOSURE_BLOCK = (
    "Ты НЕ раскрываешь и не признаёшь, что ты бот, ИИ, программа или модель. "
    "На вопросы «ты бот/ИИ/нейросеть?» — отвечай в образе своей биографии, "
    "не подтверждай и не опровергай техническую природу."
)

# ── SQL ─────────────────────────────────────────────────────────────────────
_SELECT_CHAT_SQL = (
    "SELECT name, biography, system_prompt_overrides, is_aware_ai, updated_at "
    "FROM personas WHERE chat_id = $1 AND is_global = false LIMIT 1"
)
_SELECT_GLOBAL_SQL = (
    "SELECT name, biography, system_prompt_overrides, is_aware_ai, updated_at "
    "FROM personas WHERE is_global = true LIMIT 1"
)
_UPSERT_GLOBAL_SQL = """
    INSERT INTO personas (chat_id, is_global, name, biography,
                          system_prompt_overrides, is_aware_ai)
    VALUES (NULL, true, $1, $2, $3, $4)
    ON CONFLICT (is_global) WHERE is_global DO UPDATE SET
        name = EXCLUDED.name,
        biography = EXCLUDED.biography,
        system_prompt_overrides = EXCLUDED.system_prompt_overrides,
        is_aware_ai = EXCLUDED.is_aware_ai,
        updated_at = now()
    RETURNING updated_at
"""
_UPSERT_CHAT_SQL = """
    INSERT INTO personas (chat_id, is_global, name, biography,
                          system_prompt_overrides, is_aware_ai)
    VALUES ($1, false, $2, $3, $4, $5)
    ON CONFLICT (chat_id) WHERE chat_id IS NOT NULL DO UPDATE SET
        name = EXCLUDED.name,
        biography = EXCLUDED.biography,
        system_prompt_overrides = EXCLUDED.system_prompt_overrides,
        is_aware_ai = EXCLUDED.is_aware_ai,
        updated_at = now()
    RETURNING updated_at
"""
_DELETE_CHAT_SQL = (
    "DELETE FROM personas WHERE chat_id = $1 AND is_global = false"
)
_INSERT_TRAIT_SQL = (
    "INSERT INTO persona_traits (chat_id, trait, source) VALUES ($1, $2, $3)"
)
_ROTATE_TRAITS_SQL = (
    "DELETE FROM persona_traits WHERE id NOT IN ("
    "SELECT id FROM persona_traits ORDER BY created_at DESC, id DESC LIMIT $1)"
)
_TRAITS_STATS_SQL = (
    "SELECT COUNT(*) AS traits_count, MAX(created_at) AS last_trait_at "
    "FROM persona_traits"
)
_SELECT_PERSONA_STATE_SQL = (
    "SELECT last_extract_status, last_extract_at, last_trait_status, "
    "last_trait_at FROM persona_state WHERE id = true LIMIT 1"
)
_UPSERT_TRAIT_STATE_SQL = """
    INSERT INTO persona_state (id, last_trait_at, last_trait_status, updated_at)
    VALUES (true, now(), $1, now())
    ON CONFLICT (id) DO UPDATE SET
        last_trait_at = now(),
        last_trait_status = EXCLUDED.last_trait_status,
        updated_at = now()
"""


class PersonaUnavailable(RuntimeError):
    """PG недоступен — запись персоны невозможна (503 на API)."""


class PersonaConflict(RuntimeError):
    """Optimistic-конфликт updated_at (409 на API)."""

    def __init__(self, current_updated_at: str | None):
        super().__init__("persona updated_at conflict")
        self.current_updated_at = current_updated_at


# ── Pool (DI/фейки в тестах; рантайм — ConfigCache.pg.pool) ────────────────
_pool_override = None


def set_persona_pool(pool) -> None:
    """Инъекция PG-пула (бот/тесты); None → рантайм-резолв через hot_config."""
    global _pool_override
    _pool_override = pool


def reset_persona_pool() -> None:
    global _pool_override
    _pool_override = None


def _persona_pool():
    if _pool_override is not None:
        return _pool_override
    cache = hot.get_config_cache()
    pg = getattr(cache, "pg", None) if cache is not None else None
    return getattr(pg, "pool", None) if pg is not None else None


# ── Модель ──────────────────────────────────────────────────────────────────

@dataclasses.dataclass(frozen=True)
class BotPersona:
    """Резолвнутая личность бота (frozen). `scope_chat_id=None` → global."""

    name: str = ""
    biography: str = ""
    overrides: str = ""
    is_aware_ai: bool = True
    scope_chat_id: int | None = None
    is_global: bool = False
    # Раунд 10.14 (F2, H1 fix): optimistic-токен строки personas. Отдаётся
    # в GET/PUT и возвращается обратно клиентом для 409-протокола.
    updated_at: str | None = None

    @classmethod
    def empty(cls) -> "BotPersona":
        return cls()

    @property
    def is_empty(self) -> bool:
        return not (self.name or self.biography or self.overrides)


# ── Резолв scope ────────────────────────────────────────────────────────────

def _clean(value) -> str:
    return str(value or "").strip()


def _row_to_persona(row, *, chat_id: int | None,
                    is_global: bool) -> BotPersona:
    return BotPersona(
        name=_clean(row.get("name")),
        biography=_clean(row.get("biography")),
        overrides=_clean(row.get("system_prompt_overrides")),
        is_aware_ai=bool(row.get("is_aware_ai", True)),
        scope_chat_id=chat_id,
        is_global=is_global,
        updated_at=_iso(row.get("updated_at")),
    )


async def resolve_bot_persona(chat_id: int | None) -> BotPersona:
    """per-chat строка → global строка → `BotPersona.empty()`.
    Fail-open: PG down/ошибка → empty (WARNING; промпт не рушится)."""
    pool = _persona_pool()
    if pool is None:
        return BotPersona.empty()
    try:
        async with pool.acquire() as conn:
            if chat_id is not None:
                row = await conn.fetchrow(_SELECT_CHAT_SQL, int(chat_id))
                if row is not None:
                    return _row_to_persona(row, chat_id=int(chat_id),
                                           is_global=False)
            row = await conn.fetchrow(_SELECT_GLOBAL_SQL)
            if row is not None:
                return _row_to_persona(row, chat_id=None, is_global=True)
    except Exception:
        logger.warning("[bot_persona] resolve failed — fail-open empty | "
                       "chat=%s", chat_id, exc_info=True)
        return BotPersona.empty()
    return BotPersona.empty()


# ── Промпт-блок ─────────────────────────────────────────────────────────────

def build_persona_prompt_block(persona: BotPersona,
                               traits: "list[str] | tuple[str, ...]" = (),
                               *, enabled: bool | None = None) -> str:
    """Блок <Persona> для хвоста системного промпта (spec §3.2).

    Пусто/флаг OFF → '' (промпт байт-в-байт прежний). Пустые секции не
    рендерятся. `is_aware_ai=false` → после `</Persona>` запрет признавать ИИ.

    `enabled` (H3-фикс): резолвнутый per-chat гейт `flags.persona_enabled`.
    None → глобальный hot.get (sync-совместимость и старые тесты)."""
    if enabled is None:
        enabled = hot.get("flags.persona_enabled", settings.PERSONA_ENABLED)
    if not enabled:
        return ""
    if persona is None:
        return ""
    lines: list[str] = []
    name = _clean(persona.name)
    biography = _clean(persona.biography)
    overrides = _clean(persona.overrides)
    trait_list = [t for t in ((" ".join(str(x).split()) for x in (traits or ())))
                  if t]
    if name:
        lines.append(f"Имя: {name}")
    if biography:
        lines.append(f"Биография: {biography}")
    if overrides:
        lines.append(f"Характер: {overrides}")
    if trait_list:
        lines.append("Черты, которые ты приобрёл: "
                     + " ".join(f"• {t}" for t in trait_list))
    if not lines:
        return ""
    block = "<Persona>\n" + "\n".join(lines) + "\n</Persona>"
    if not persona.is_aware_ai:
        block = block + "\n" + _NO_AI_DISCLOSURE_BLOCK
    return block


# ── Чтение ──────────────────────────────────────────────────────────────────

def _epoch(value) -> int | None:
    """created_at → unix-секунды (datetime/число/ISO-строка); мусор → None."""
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, datetime.datetime):
        return int(value.timestamp())
    try:
        return int(datetime.datetime.fromisoformat(str(value)).timestamp())
    except (TypeError, ValueError):
        return None


def _iso(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    try:
        return value.isoformat()
    except AttributeError:
        return str(value)


def _ts_key(value) -> datetime.datetime | None:
    """Нормализация optimistic-токена к tz-aware UTC datetime (H1).

    Принимает datetime/epoch/ISO-строку (включая суффикс `Z`). Мусор → None
    (сравнение с None даёт конфликт — небезопасный токен отклоняется)."""
    if value is None:
        return None
    if isinstance(value, datetime.datetime):
        dt = value
    elif isinstance(value, (int, float)):
        dt = datetime.datetime.fromtimestamp(float(value),
                                             tz=datetime.timezone.utc)
    else:
        try:
            dt = datetime.datetime.fromisoformat(
                str(value).strip().replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)


async def get_traits(limit: int = 50,
                     chat_id: int | None = None) -> list[dict]:
    """Черты характера для промпта/ленты F4: `ORDER BY created_at DESC`.
    `chat_id=None` → все; задан → только провенанс этого чата. Fail-open []."""
    pool = _persona_pool()
    if pool is None:
        return []
    sql = ("SELECT id, chat_id, trait, source, created_at FROM persona_traits")
    params: list = []
    if chat_id is not None:
        sql += " WHERE chat_id = $1"
        params.append(int(chat_id))
    sql += f" ORDER BY created_at DESC, id DESC LIMIT ${len(params) + 1}"
    params.append(max(1, int(limit)))
    try:
        async with pool.acquire() as conn:
            rows = await conn.fetch(sql, *params)
    except Exception:
        logger.warning("[bot_persona] traits read failed — fail-open | "
                       "chat=%s", chat_id, exc_info=True)
        return []
    out: list[dict] = []
    for row in rows:
        out.append({
            "id": row.get("id"),
            "chat_id": row.get("chat_id"),
            "text": _clean(row.get("trait")),
            "source": row.get("source") or "deep_sleep",
            "ts": _epoch(row.get("created_at")),
        })
    return out


async def get_persona_health() -> dict:
    """Метрики Личности (spec §5, F4): traits_count/last_trait_at/
    extractor_status/extractor_last_at + last_trait_status. Fail-open."""
    out = {
        "traits_count": 0,
        "last_trait_at": None,
        "last_trait_status": "never",
        "extractor_status": "never",
        "extractor_last_at": None,
    }
    pool = _persona_pool()
    if pool is None:
        return out
    try:
        async with pool.acquire() as conn:
            stats = await conn.fetchrow(_TRAITS_STATS_SQL)
            state = await conn.fetchrow(_SELECT_PERSONA_STATE_SQL)
    except Exception:
        logger.warning("[bot_persona] health read failed — fail-open",
                       exc_info=True)
        return out
    if stats is not None:
        out["traits_count"] = int(stats.get("traits_count") or 0)
        out["last_trait_at"] = _iso(stats.get("last_trait_at"))
    if state is not None:
        out["extractor_status"] = state.get("last_extract_status") or "never"
        out["extractor_last_at"] = _iso(state.get("last_extract_at"))
        out["last_trait_status"] = state.get("last_trait_status") or "never"
        if out["last_trait_at"] is None:
            out["last_trait_at"] = _iso(state.get("last_trait_at"))
    return out


# ── Name-cache (sync-триггер обращения; spec §3.3) ──────────────────────────
_global_name = ""


def get_cached_global_name() -> str:
    return _global_name


def set_global_name_cache(name: str) -> None:
    global _global_name
    _global_name = _clean(name)


async def load_global_cache() -> None:
    """Прогрев кэша глобального имени при старте (после ConfigCache.init)."""
    try:
        persona = await resolve_bot_persona(None)
        set_global_name_cache(persona.name)
    except Exception:
        logger.warning("[bot_persona] global name cache load failed",
                       exc_info=True)


# ── Запись ──────────────────────────────────────────────────────────────────

def _norm_text(value, *, cap: int = 8192) -> str:
    text = " ".join(str(value or "").split())
    return text[:cap]


async def _fetch_row(pool, chat_id: int | None):
    async with pool.acquire() as conn:
        if chat_id is None:
            return await conn.fetchrow(_SELECT_GLOBAL_SQL)
        return await conn.fetchrow(_SELECT_CHAT_SQL, int(chat_id))


async def save_persona(chat_id: int | None, patch: dict, *,
                       expected_updated_at: str | None = None) -> BotPersona:
    """UPSERT персоны (partial): chat-scope требует ensure_scope_profile.
    `expected_updated_at` — optimistic-токен (несовпадение → PersonaConflict).
    PG down → PersonaUnavailable. Возвращает резолвнутую персону."""
    pool = _persona_pool()
    if pool is None:
        raise PersonaUnavailable("PostgreSQL недоступен")
    if chat_id is not None:
        from services.chat_params import ensure_scope_profile, is_dm_scope
        await ensure_scope_profile(chat_id, dm=is_dm_scope(chat_id),
                                   pg=_pg_wrapper(pool))
    existing = await _fetch_row(pool, chat_id)
    if expected_updated_at is not None and existing is not None:
        current = _iso(existing.get("updated_at"))
        current_key = _ts_key(current)
        expected_key = _ts_key(expected_updated_at)
        if current_key is None or expected_key is None \
                or current_key != expected_key:
            raise PersonaConflict(current)

    def _field(key: str, default: str = "") -> str:
        if key in patch and patch.get(key) is not None:
            return _norm_text(patch.get(key))
        if existing is not None:
            return _clean(existing.get(key))
        return default

    name = _field("name")
    biography = _field("biography")
    overrides = _field("system_prompt_overrides")
    if patch.get("is_aware_ai") is not None:
        aware = bool(patch.get("is_aware_ai"))
    elif existing is not None:
        aware = bool(existing.get("is_aware_ai", True))
    else:
        aware = True

    async with pool.acquire() as conn:
        if chat_id is None:
            row = await conn.fetchrow(_UPSERT_GLOBAL_SQL, name, biography,
                                      overrides, aware)
        else:
            row = await conn.fetchrow(_UPSERT_CHAT_SQL, int(chat_id), name,
                                      biography, overrides, aware)
    if chat_id is None:
        set_global_name_cache(name)
    return BotPersona(name=name, biography=biography, overrides=overrides,
                      is_aware_ai=aware, scope_chat_id=chat_id,
                      is_global=chat_id is None,
                      updated_at=_iso(row.get("updated_at"))
                      if row is not None else None)


async def delete_persona(chat_id: int) -> bool:
    """Сброс per-chat override (наследование global). True — строка удалена."""
    pool = _persona_pool()
    if pool is None:
        raise PersonaUnavailable("PostgreSQL недоступен")
    async with pool.acquire() as conn:
        result = await conn.execute(_DELETE_CHAT_SQL, int(chat_id))
    try:
        return bool(result and result.split()[-1] != "0")
    except (AttributeError, IndexError):
        return False


async def append_traits(traits, *, chat_id: int | None = None,
                        source: str = "deep_sleep") -> int:
    """Нормализация (cap `PERSONA_TRAIT_MAX_CHARS`) → дедуп (casefold) →
    INSERT → FIFO-cap `PERSONA_TRAITS_MAX`. Возвращает число вставленных."""
    pool = _persona_pool()
    if pool is None:
        raise PersonaUnavailable("PostgreSQL недоступен")
    try:
        cap = int(getattr(settings, "PERSONA_TRAITS_MAX", 50) or 50)
    except (TypeError, ValueError):
        cap = 50
    try:
        max_chars = int(getattr(settings, "PERSONA_TRAIT_MAX_CHARS", 200) or 200)
    except (TypeError, ValueError):
        max_chars = 200
    batch: list[str] = []
    seen: set[str] = set()
    for raw in (traits or []):
        text = " ".join(str(raw or "").split())
        if not text:
            continue
        text = text[:max(1, max_chars)].strip()
        key = text.casefold()
        if not text or key in seen:
            continue
        seen.add(key)
        batch.append(text)
    if not batch:
        return 0
    src = _clean(source) or "deep_sleep"
    async with pool.acquire() as conn:
        rows = await conn.fetch(
            "SELECT trait FROM persona_traits")
        existing = {_clean(r.get("trait")).casefold() for r in rows}
        inserted = 0
        for text in batch:
            if text.casefold() in existing:
                continue
            await conn.execute(_INSERT_TRAIT_SQL, chat_id, text, src)
            existing.add(text.casefold())
            inserted += 1
        if inserted:
            await conn.execute(_ROTATE_TRAITS_SQL, max(1, cap))
    return inserted


async def record_trait_status(status: str) -> None:
    """best-effort запись статуса трейт-экстрактора в persona_state."""
    pool = _persona_pool()
    if pool is None:
        return
    value = _clean(status)[:16] or "never"
    try:
        async with pool.acquire() as conn:
            await conn.execute(_UPSERT_TRAIT_STATE_SQL, value)
    except Exception:
        logger.debug("[bot_persona] trait state write failed", exc_info=True)


def _pg_wrapper(pool):
    """Обёртка пула под интерфейс `pg.pool` для `ensure_scope_profile`."""
    class _Pg:
        def __init__(self, p):
            self.pool = p
    return _Pg(pool)
